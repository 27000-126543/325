import re

files_tags = {
    'app/routers/dispatch.py': '1.Dispatch',
    'app/routers/irrigation.py': '2.Irrigation',
    'app/routers/quality.py': '3.WaterQuality',
    'app/routers/ecological.py': '4.EcologicalFlow',
    'app/routers/trade.py': '5.WaterRightsTrade',
    'app/routers/transfer.py': '6.CrossRegionTransfer',
    'app/routers/maintenance.py': '7.Maintenance',
    'app/routers/reports.py': '8.DailyReports',
}

for fp, tag in files_tags.items():
    with open(fp, 'r', encoding='utf-8') as f:
        content = f.read()
    pattern = r'APIRouter\(prefix="([^"]+)",\s*tags=\["[^"]*"\]\)'
    def repl(m):
        prefix = m.group(1)
        return f'APIRouter(prefix="{prefix}", tags=["{tag}"])'
    new_content = re.sub(pattern, repl, content)
    with open(fp, 'w', encoding='utf-8') as f:
        f.write(new_content)
    print(f'Fixed: {fp}')
