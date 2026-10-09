"""Register the already-recorded demo policy referenced by the sample; no policy execution."""
import csv
import json
from .adapter import ROOT
from .verify import REPORTS,write

def main():
    prior=json.loads((ROOT/'reports/qci3/loopback_demo.json').read_text())
    policy=prior['policy'];version=policy['policy_version']
    # Preserve the original saved configuration as provenance only. Its old mock
    # URL is not a live endpoint and this helper never constructs an alarm engine.
    path=REPORTS/'referenced_alarm_policy.json';write(path,policy)
    registry=ROOT/'Experiment_Tracking/alert_policy_registry.csv'
    with registry.open(encoding='utf-8',newline='') as handle:
        reader=csv.DictReader(handle);fields=reader.fieldnames
        if any(row['policy_version']==version for row in reader):return
    row=dict(policy_version=version,sprint='Sprint 2',task='QCI-5',detector_model_version=policy['expected_model_version'],
        threshold_config=path.relative_to(ROOT).as_posix(),clear_policy='Existing QCI-3 explicit resolution; recurrence new activation ID',
        status='historical_research_demo_reference_only',benchmark='existing_QCI3_original_event_digest_bound_pdf',
        notes=json.dumps(dict(origin='reports/qci3/loopback_demo.json',rules_unchanged=True,
            production_rule_approval=False,hardware_siren_validated=False,purpose='Register actual stored policy lineage for QCI-5 reporting only'),separators=(',',':')))
    with registry.open('a',encoding='utf-8',newline='') as handle:csv.DictWriter(handle,fieldnames=fields).writerow({field:row.get(field,'') for field in fields})
    print('Registered existing historical demo policy reference: '+version)
if __name__=='__main__':main()
