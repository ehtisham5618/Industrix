"""Existing offline CLI, powered by the same QCI-5 service as API downloads."""
import argparse
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from Backend.incidents.repository import IncidentRepository
from QCI_5_Incident_PDF.adapter import Adapter,configuration,local_path
from QCI_5_Incident_PDF.service import PDFService

def main():
    parser=argparse.ArgumentParser(description='Existing local incident/event to ReportLab PDF')
    parser.add_argument('--incident-id',required=True)
    parser.add_argument('--output',type=Path,help='Explicit trusted local report output root')
    parser.add_argument('--database',type=Path,help='Existing legacy incident database')
    parser.add_argument('--snapshots',type=Path)
    parser.add_argument('--quality-database',type=Path,help='Existing QCI-3 database; no new store created')
    args=parser.parse_args()
    try:
        config=configuration()
        if args.output:config.output_dir=str(local_path(args.output))
        if args.quality_database:config.quality_database=str(local_path(args.quality_database))
        repo=IncidentRepository(args.database,args.snapshots,initialize=False)
        result=PDFService(Adapter(repo,config)).generate(args.incident_id)
        print(result.model_dump_json(indent=2))
        return 0 if result.status=='SUCCESS' else 1
    except Exception as exc:
        print('PDF_EXPORT_FAILED: '+type(exc).__name__,file=sys.stderr);return 1

if __name__=='__main__':raise SystemExit(main())
