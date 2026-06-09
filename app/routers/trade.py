from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional, List
from datetime import datetime, date
import uuid
import statistics

from app.database import get_db
from app.models import (
    WaterTradeOrder, WaterTradeContract, OrderStatus,
    WaterRight, TradePriceHistory, User
)
from app.schemas import (
    TradeOrderCreate, TradeOrderOut, TradeContractOut,
    ContractApprove, ResponseModel, PaginatedResponse
)
from app.services import NotificationService

router = APIRouter(prefix="/api/v1/trade", tags=["5.WaterRightsTrade"])


def generate_order_no():
    return f"TO{datetime.utcnow().strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:6].upper()}"


def generate_contract_no():
    return f"TC{datetime.utcnow().strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:6].upper()}"


@router.post("/orders", response_model=ResponseModel, summary="提交买卖需求")
def create_trade_order(data: TradeOrderCreate, db: Session = Depends(get_db)):
    if data.order_type not in ("buy", "sell"):
        raise HTTPException(400, "order_type必须是buy或sell")
    if data.water_volume <= 0 or data.expected_price <= 0:
        raise HTTPException(400, "水量和价格必须大于0")

    wr = db.query(WaterRight).filter(WaterRight.id == data.water_right_id).first()
    if not wr:
        raise HTTPException(404, "水权不存在")

    if data.order_type == "sell":
        if wr.remaining_amount < data.water_volume:
            raise HTTPException(400, f"水权余量{wr.remaining_amount}不足，无法卖出{data.water_volume}")

    order = WaterTradeOrder(
        **data.model_dump(),
        order_no=generate_order_no(),
        status=OrderStatus.OPEN
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    NotificationService.notify_trade(
        db, 0,
        f"新交易需求: {'买入' if data.order_type == 'buy' else '卖出'}",
        f"用户{data.user_id} {data.order_type} 水量:{data.water_volume}m³ "
        f"期望单价:¥{data.expected_price}/m³ 区域:{data.region}"
    )

    return ResponseModel(data=TradeOrderOut.model_validate(order).model_dump())


@router.get("/orders", response_model=PaginatedResponse, summary="交易需求列表")
def list_orders(
    order_type: Optional[str] = None, status: Optional[OrderStatus] = None,
    user_id: Optional[int] = None, region: Optional[str] = None,
    page: int = 1, page_size: int = 20, db: Session = Depends(get_db)
):
    q = db.query(WaterTradeOrder)
    if order_type:
        q = q.filter(WaterTradeOrder.order_type == order_type)
    if status:
        q = q.filter(WaterTradeOrder.status == status)
    if user_id:
        q = q.filter(WaterTradeOrder.user_id == user_id)
    if region:
        q = q.filter(WaterTradeOrder.region == region)
    total = q.count()
    items = q.order_by(WaterTradeOrder.id.desc()).offset((page-1)*page_size).limit(page_size).all()
    return PaginatedResponse(
        total=total, page=page, page_size=page_size,
        data=[TradeOrderOut.model_validate(i) for i in items]
    )


@router.post("/match", response_model=ResponseModel, summary="系统自动匹配交易并生成合同")
def auto_match_trades(region: Optional[str] = None, basin: Optional[str] = None,
                     db: Session = Depends(get_db)):
    buy_orders = db.query(WaterTradeOrder).filter(
        WaterTradeOrder.order_type == "buy",
        WaterTradeOrder.status == OrderStatus.OPEN
    ).all()
    sell_orders = db.query(WaterTradeOrder).filter(
        WaterTradeOrder.order_type == "sell",
        WaterTradeOrder.status == OrderStatus.OPEN
    ).all()

    today = date.today()
    history = db.query(TradePriceHistory).filter(
        TradePriceHistory.trade_date >= date(today.year, today.month, 1)
    ).all()
    historical_avg = statistics.mean([h.avg_price for h in history]) if history else None

    if region:
        buy_orders = [o for o in buy_orders if o.region == region]
        sell_orders = [o for o in sell_orders if o.region == region]

    contracts = []
    matched_count = 0

    for buy in buy_orders:
        best_match = None
        best_score = -1

        for sell in sell_orders:
            if sell.status != OrderStatus.OPEN:
                continue
            if buy.user_id == sell.user_id:
                continue

            price_diff = abs(buy.expected_price - sell.expected_price)
            price_ratio = min(buy.expected_price, sell.expected_price) / max(buy.expected_price, sell.expected_price)
            volume_match = 1 - abs(buy.water_volume - sell.water_volume) / max(buy.water_volume, sell.water_volume)
            region_match = 1.0 if buy.region == sell.region else 0.5

            score = price_ratio * 0.4 + volume_match * 0.4 + region_match * 0.2

            if historical_avg:
                mid = (buy.expected_price + sell.expected_price) / 2
                if abs(mid - historical_avg) / historical_avg > 0.3:
                    score *= 0.7

            if score > best_score and buy.expected_price >= sell.expected_price:
                best_score = score
                best_match = sell

        if best_match and best_score >= 0.5:
            trade_volume = min(buy.water_volume, best_match.water_volume)
            trade_price = (buy.expected_price + best_match.expected_price) / 2
            total_amount = round(trade_volume * trade_price, 2)

            contract = WaterTradeContract(
                contract_no=generate_contract_no(),
                buy_order_id=buy.id,
                sell_order_id=best_match.id,
                buyer_id=buy.user_id,
                seller_id=best_match.user_id,
                trade_volume=trade_volume,
                unit_price=round(trade_price, 2),
                total_amount=total_amount,
                historical_avg_price=historical_avg,
                approval_status=OrderStatus.APPROVING,
                effective_date=today,
                expiry_date=date(today.year + 1, today.month, today.day) if today.month < 12 else date(today.year + 1, today.month, 28),
                remarks=f"系统自动匹配，匹配得分{round(best_score, 3)}。买方出价¥{buy.expected_price}，卖方出价¥{best_match.expected_price}"
            )
            db.add(contract)

            buy.status = OrderStatus.MATCHED
            buy.matched_order_id = best_match.id
            buy.final_price = round(trade_price, 2)

            best_match.status = OrderStatus.MATCHED
            best_match.matched_order_id = buy.id
            best_match.final_price = round(trade_price, 2)

            contracts.append(contract)
            matched_count += 1

    db.commit()

    for c in contracts:
        db.refresh(c)
        NotificationService.notify_trade(
            db, c.id,
            f"交易合同待审批: {c.contract_no}",
            f"买方用户{c.buyer_id} ↔ 卖方用户{c.seller_id}，"
            f"水量:{c.trade_volume}m³，单价:¥{c.unit_price}，总额:¥{c.total_amount:,.2f}，"
            f"请流域管理机构审批。",
            user_ids=[c.buyer_id, c.seller_id]
        )

    return ResponseModel(data={
        "matched_count": matched_count,
        "historical_avg_price": historical_avg,
        "contracts": [TradeContractOut.model_validate(c).model_dump() for c in contracts]
    })


@router.get("/contracts", response_model=PaginatedResponse, summary="交易合同列表")
def list_contracts(
    status: Optional[OrderStatus] = None, buyer_id: Optional[int] = None,
    seller_id: Optional[int] = None, page: int = 1, page_size: int = 20,
    db: Session = Depends(get_db)
):
    q = db.query(WaterTradeContract)
    if status:
        q = q.filter(WaterTradeContract.approval_status == status)
    if buyer_id:
        q = q.filter(WaterTradeContract.buyer_id == buyer_id)
    if seller_id:
        q = q.filter(WaterTradeContract.seller_id == seller_id)
    total = q.count()
    items = q.order_by(WaterTradeContract.id.desc()).offset((page-1)*page_size).limit(page_size).all()
    return PaginatedResponse(
        total=total, page=page, page_size=page_size,
        data=[TradeContractOut.model_validate(i) for i in items]
    )


@router.post("/contracts/approve", response_model=ResponseModel, summary="流域管理机构审批合同")
def approve_contract(data: ContractApprove, db: Session = Depends(get_db)):
    contract = db.query(WaterTradeContract).filter(
        WaterTradeContract.id == data.contract_id
    ).first()
    if not contract:
        raise HTTPException(404, "合同不存在")
    if contract.approval_status != OrderStatus.APPROVING:
        raise HTTPException(400, "合同不在审批状态")

    if data.is_approved:
        contract.approval_status = OrderStatus.EFFECTIVE
        contract.approved_by = data.approver_id
        contract.approved_at = datetime.utcnow()

        sell_order = db.query(WaterTradeOrder).filter(
            WaterTradeOrder.id == contract.sell_order_id
        ).first()
        sell_right = db.query(WaterRight).filter(
            WaterRight.user_id == contract.seller_id
        ).order_by(WaterRight.id.desc()).first()
        buy_right = db.query(WaterRight).filter(
            WaterRight.user_id == contract.buyer_id
        ).order_by(WaterRight.id.desc()).first()

        if sell_right:
            sell_right.used_amount += contract.trade_volume
            sell_right.remaining_amount = max(0, sell_right.annual_quota - sell_right.used_amount)

        if buy_right:
            buy_right.remaining_amount += contract.trade_volume

        if sell_order:
            sell_order.status = OrderStatus.EFFECTIVE

        buy_order = db.query(WaterTradeOrder).filter(
            WaterTradeOrder.id == contract.buy_order_id
        ).first()
        if buy_order:
            buy_order.status = OrderStatus.EFFECTIVE

        today = date.today()
        price_hist = TradePriceHistory(
            basin="默认流域",
            region="",
            trade_date=today,
            avg_price=contract.unit_price,
            total_volume=contract.trade_volume,
            transaction_count=1,
            price_trend="flat"
        )
        db.add(price_hist)

        msg_title = f"交易合同已生效: {contract.contract_no}"
        msg_content = (
            f"合同审批通过！水量:{contract.trade_volume}m³，单价:¥{contract.unit_price}，"
            f"总额:¥{contract.total_amount:,.2f}，已划转水权额度。"
        )
    else:
        contract.approval_status = OrderStatus.CANCELLED
        contract.approved_by = data.approver_id
        contract.approved_at = datetime.utcnow()
        contract.remarks = (contract.remarks or "") + f" | 拒绝原因: {data.remarks or '未说明'}"

        sell_order = db.query(WaterTradeOrder).filter(
            WaterTradeOrder.id == contract.sell_order_id
        ).first()
        buy_order = db.query(WaterTradeOrder).filter(
            WaterTradeOrder.id == contract.buy_order_id
        ).first()
        if sell_order:
            sell_order.status = OrderStatus.OPEN
            sell_order.matched_order_id = None
        if buy_order:
            buy_order.status = OrderStatus.OPEN
            buy_order.matched_order_id = None

        msg_title = f"交易合同被拒绝: {contract.contract_no}"
        msg_content = f"审批人拒绝原因: {data.remarks or '未说明'}"

    db.commit()
    db.refresh(contract)

    NotificationService.notify_trade(
        db, contract.id, msg_title, msg_content,
        user_ids=[contract.buyer_id, contract.seller_id]
    )

    return ResponseModel(data=TradeContractOut.model_validate(contract).model_dump())


@router.get("/price-history", response_model=ResponseModel, summary="历史成交价查询")
def get_price_history(
    start_date: Optional[date] = None, end_date: Optional[date] = None,
    basin: Optional[str] = None, db: Session = Depends(get_db)
):
    q = db.query(TradePriceHistory)
    if start_date:
        q = q.filter(TradePriceHistory.trade_date >= start_date)
    if end_date:
        q = q.filter(TradePriceHistory.trade_date <= end_date)
    if basin:
        q = q.filter(TradePriceHistory.basin == basin)
    items = q.order_by(TradePriceHistory.trade_date.desc()).limit(90).all()

    prices = [h.avg_price for h in items]
    summary = {
        "latest_avg": prices[0] if prices else 0,
        "30d_avg": statistics.mean(prices[:30]) if len(prices) >= 30 else (statistics.mean(prices) if prices else 0),
        "max": max(prices) if prices else 0,
        "min": min(prices) if prices else 0,
        "trend": items[0].price_trend if items else "flat"
    }

    return ResponseModel(data={
        "summary": summary,
        "records": [{
            "date": h.trade_date.isoformat(), "avg_price": h.avg_price,
            "total_volume": h.total_volume, "transaction_count": h.transaction_count
        } for h in items]
    })
