"""Conservative distinction between a live call date and replay availability."""
import re
from datetime import date

MONTHS={name.lower():i for i,name in enumerate(['January','February','March','April','May','June','July','August','September','October','November','December'],1)}
DATE_RE=re.compile(r'\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?',re.I)
CALL_RE=re.compile(r'conference call|earnings call|results call',re.I)


def confirm_live_call(candidate_date,snippet):
    target=date.fromisoformat(candidate_date)
    found=False
    rejected_replay=False
    for match in DATE_RE.finditer(snippet):
        month=next(v for k,v in MONTHS.items() if k.startswith(match[1].lower()[:3]))
        try: parsed=date(int(match[3] or target.year),month,int(match[2]))
        except ValueError: continue
        if parsed!=target: continue
        found=True
        before=snippet[max(0,match.start()-240):match.start()]
        if re.search(r'\b(replay|archiv\w*|until|through|expires?|expiration)\b',before[-140:],re.I):
            rejected_replay=True
            continue
        calls=list(CALL_RE.finditer(before))
        if not calls:
            continue
        schedule=before[calls[-1].start():]
        if re.search(r'investor (day|meeting|conference)|analyst day|summit|agenda|no later than|dividend|record date',schedule,re.I):
            continue
        if re.search(r'\b(will|hold|host|begin\w*|scheduled|on|conduct)\b',before,re.I):
            return True,'explicit_live_call_schedule' if match[3] else 'explicit_month_day_year_corroborated_by_reported_date'
    return False,('replay_or_archive_date' if rejected_replay else 'no_live_call_schedule' if found else 'candidate_date_not_in_excerpt')
