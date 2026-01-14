import re
from typing import List, Dict, Tuple


def normalize_split_spec(s: str) -> str:
    s = (s or '').replace('\u00a0', ' ').strip()
    s = s.replace('–', '-').replace('—', '-').replace('‑', '-')
    s = re.sub(r'\s+', ' ', s)
    s = re.sub(r'\s*,\s*', ', ', s)
    return s.strip()


def parse_split_groups(ranges_text: str) -> List[Dict[str, object]]:
    ranges_text = normalize_split_spec(ranges_text)
    if not ranges_text:
        raise ValueError('Page ranges are required')

    groups_raw = [g.strip() for g in re.split(r'[;\n]+', ranges_text) if g.strip()]
    if not groups_raw:
        raise ValueError('Page ranges are required')

    groups: List[Dict[str, object]] = []
    for group_raw in groups_raw:
        parts = [p.strip() for p in group_raw.split(',') if p.strip()]
        if not parts:
            raise ValueError(f"Invalid group: '{group_raw}'")

        segments: List[Tuple[int, int]] = []
        normalized_parts: List[str] = []
        for part in parts:
            part = normalize_split_spec(part)
            m_range = re.match(r'^(\d+)\s*-\s*(\d+)$', part)
            m_single = re.match(r'^(\d+)$', part)
            if m_range:
                start = int(m_range.group(1))
                end = int(m_range.group(2))
            elif m_single:
                start = int(m_single.group(1))
                end = start
            else:
                raise ValueError(f"Invalid segment: '{part}'. Use 1-4 or 55")

            if start < 1 or end < 1 or end < start:
                raise ValueError(f"Invalid segment: '{part}'. Ensure start/end are positive and end >= start")

            segments.append((start, end))
            normalized_parts.append(f"{start}-{end}" if start != end else f"{start}")

        label = ', '.join(normalized_parts)
        groups.append({'label': label, 'segments': segments})

    return groups
