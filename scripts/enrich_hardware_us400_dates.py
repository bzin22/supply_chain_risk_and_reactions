"""Apply the reviewed all-call release ledger; never fill by a date window."""
import argparse
from pathlib import Path
import pandas as pd
from analysis.hardware_us400.inventory import FINAL,read
from analysis.hardware_us400.release_dates import validate_decisions,apply_decision
from analysis.hardware_us400.rebuild_audited import sic_history,PACKAGE
from analysis.primary_event_study import core


def enrich(source,output):
    if output.exists():raise FileExistsError('Choose a new prepared input')
    rows=read(source)
    decisions=pd.read_csv(PACKAGE/'date_audit.csv.gz',dtype=str,keep_default_na=False).to_dict('records')
    by=validate_decisions(rows,decisions);history=sic_history(core.ROOT)
    corrected=[]
    for row in rows:
        row=apply_decision(row,by[row['call_id']]);row.update(core.assign_sic(row,history));corrected.append(row)
    core.write_csv(output,corrected)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',type=Path,default=FINAL/'prepared_calls.csv');p.add_argument('--output',type=Path,required=True);a=p.parse_args();enrich(a.input,a.output)
