"""
Audit test for vast_client and app logic.
"""
from vast_client import VastAIClient, load_preferences, save_preferences
import pandas as pd

def run_tests():
    print("1. Testing VastAIClient machine functions...")
    all_machs = VastAIClient.get_all_tracked_machines_summary(days_back=7)
    print(f"   Tracked machines found: {len(all_machs)}")
    assert not all_machs.empty, "No machines found in DB!"

    test_id = int(all_machs.iloc[0]["machine_id"])
    print(f"2. Testing machine history for ID {test_id}...")
    hist_df = VastAIClient.get_machine_history([test_id], days_back=7)
    print(f"   History rows: {len(hist_df)}")
    assert not hist_df.empty, "No history found!"

    print("3. Testing calculate_machine_detailed_metrics...")
    metrics = VastAIClient.calculate_machine_detailed_metrics(hist_df)
    print(f"   Machine ID: {metrics['machine_id']}")
    print(f"   GPU: {metrics['display_name']} ({metrics['num_gpus']}x)")
    print(f"   Occupancy: {metrics['occupancy_pct']}%")
    print(f"   Status: {metrics['latest_status']}")
    print(f"   Latest price: ${metrics['latest_price_total']}/hr")
    print(f"   Total earned: ${metrics['total_earned_usd']}")
    print(f"   Projected monthly: ${metrics['projected_monthly_usd']}")

    print("4. Testing Host Fleet functions...")
    client = VastAIClient()
    host_live = client.fetch_hosts_offers([69666])
    print(f"   Host 69666 live offers: {len(host_live)}")
    if not host_live.empty:
        VastAIClient.record_raw_offers_snapshot(host_live)

    all_hosts = VastAIClient.get_all_tracked_hosts_summary(days_back=7)
    print(f"   Tracked hosts found: {len(all_hosts)}")

    host_hist = VastAIClient.get_host_history([69666], days_back=7)
    fleet = VastAIClient.calculate_host_fleet_metrics(host_hist)
    print(f"   Host 69666 fleet machines: {fleet.get('total_machines')}, GPUs: {fleet.get('total_gpus')}")
    print(f"   Fleet occupancy: {fleet.get('avg_occupancy_pct')}%")
    assert not fleet['machines_summary_df'].empty, "Fleet machines summary is empty!"

    print("5. Testing preferences loading & saving...")
    prefs = load_preferences()
    assert "watched_machine_ids" in prefs, "watched_machine_ids not in preferences!"
    assert "watched_host_ids" in prefs, "watched_host_ids not in preferences!"
    print(f"   Watched machine IDs: {prefs.get('watched_machine_ids')}")
    print(f"   Watched host IDs: {prefs.get('watched_host_ids')}")

    print("✅ All audit tests passed successfully!")

if __name__ == "__main__":
    run_tests()
