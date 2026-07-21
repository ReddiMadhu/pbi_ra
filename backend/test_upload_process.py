import os
import time
import requests

BASE_URL = "http://localhost:8000/api/v1"
SUBSET_DIR = r"c:\Users\madhu\Downloads\Tableu BI Compass\Tableu BI Compass\subset"

def run_test():
    # 1. Clear session data
    print("Clearing session data via API...")
    resp = requests.post(f"{BASE_URL}/upload/clear")
    print(f"Clear status: {resp.status_code}, Response: {resp.json()}")

    # 2. List subset files
    files = [f for f in os.listdir(SUBSET_DIR) if f.endswith(('.twb', '.twbx'))]
    print(f"Found files to upload: {files}")

    # 3. Upload each file
    for filename in files:
        filepath = os.path.join(SUBSET_DIR, filename)
        print(f"\nUploading {filename}...")
        with open(filepath, 'rb') as f:
            files_payload = {'file': (filename, f, 'application/octet-stream')}
            t0 = time.time()
            resp = requests.post(f"{BASE_URL}/upload/parse", files=files_payload)
            t1 = time.time()
            print(f"Uploaded in {t1-t0:.2f}s. Status: {resp.status_code}")
            if resp.status_code != 200:
                print(f"Error: {resp.text}")

    print("\nWaiting 90 seconds for background ontology matching to complete...")
    time.sleep(90)

    # 4. Check results
    print("\nRetrieving processed dashboards...")
    from app.db.session import SessionLocal
    from app.models.postgres import Dashboard, Workbook
    from app.models.ontology import ReportKPIMapping
    db = SessionLocal()
    try:
        workbooks = db.query(Workbook).all()
        dashboards = db.query(Dashboard).all()
        mappings = db.query(ReportKPIMapping).all()

        print(f"Total Workbooks in DB: {len(workbooks)}")
        for wb in workbooks:
            print(f"  Workbook: {wb.name} (ID: {wb.id})")

        print(f"Total Dashboards in DB: {len(dashboards)}")
        for d in dashboards:
            # count mappings for this dashboard
            d_maps = [m for m in mappings if m.report_id == str(d.id)]
            print(f"  Dashboard: {d.name} (ID: {d.id}, Sector: {d.ontology_sector}, Subdomain: {d.ontology_subdomain})")
            print(f"    - Number of KPI mappings: {len(d_maps)}")
            for m in d_maps:
                print(f"      - {m.report_kpi_name}: status={m.mapping_status}, score={m.confidence_score}, canonical={m.canonical_kpi_id}")

    finally:
        db.close()

if __name__ == "__main__":
    run_test()
