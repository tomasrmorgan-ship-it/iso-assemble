"""Explain ATEM scan limits without changing source events or media."""
import json
from pathlib import Path


def event_review(events, project, timing):
    active = {}
    transitions = []
    normalizations = []
    previous_session = None
    for event in events:
        if event.get('normalization'):
            normalizations.append(event['normalization']['warning'])
        if event['session'] != previous_session:
            for item in active.values():
                transitions.append({**item, 'incomplete': True})
            active = {}
            previous_session = event['session']
        for block in event['state'].get('mixEffectBlocks', []):
            index = block['_index_']
            if block.get('transitionActive'):
                if index not in active:
                    active[index] = dict(line=event['line'], start=event['frame'],
                        timecode=event['update']['masterTimecode'], session=event['session'],
                        block=index, type=block.get('transitionType', 'unknown'),
                        from_angle=block.get('source'), positions=[])
                value = block.get('transitionPosition')
                if value is not None and value not in active[index]['positions']:
                    active[index]['positions'].append(value)
            elif index in active:
                item = active.pop(index)
                value = block.get('transitionPosition')
                if value is not None and value not in item['positions']:
                    item['positions'].append(value)
                item.update(end=event['frame'], end_line=event['line'],
                            duration_frames=event['frame']-item['start'],
                            to_angle=block.get('source'), incomplete=False)
                item['same_angle_endpoints'] = item['from_angle'] == item['to_angle']
                item['intermediate_fader_positions_logged'] = any(0 < p < 1 for p in item['positions'])
                transitions.append(item)
    transitions.extend({**item, 'incomplete': True} for item in active.values())
    return dict(project=str(Path(project).resolve()), timing=timing.data(),
                record_count=len(events), transitions=transitions,
                normalization_notes=normalizations, scan_status='reviewing')


def write_review(report, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    transitions = report['transitions']
    lines = ['ISO Assemble — ATEM scan review', '', 'Input: '+report['project'],
             'Records: '+str(report['record_count']),
             'Recorded transitions: '+str(len(transitions)), '']
    if report.get('error'):
        lines += ['Scan stopped: '+report['error'], '']
    lines += report.get('normalization_notes', [])
    if transitions:
        incomplete = sum(t['incomplete'] for t in transitions)
        same = sum(t.get('same_angle_endpoints', False) for t in transitions)
        endpoints = sum(not t.get('intermediate_fader_positions_logged', False)
                        for t in transitions if not t['incomplete'])
        first = transitions[0]
        lines += ['', f'This build cannot reconstruct these active transitions. First: line {first["line"]}, {first["timecode"]}, {first["type"]}.',
                  f'{endpoints} complete transitions have no intermediate fader positions logged; {same} have the same camera at both endpoints; {incomplete} are incomplete.',
                  'Endpoints alone do not establish an exact manual fader curve or an unlogged intermediate camera.',
                  'Use the original program recording to inspect/recreate these intervals in the editor. The app has not replaced them with cuts.',
                  'Exact event intervals and source line numbers are in ATEM Review.json.']
    lines += ['', 'This is a diagnostic report, not a completed multicam conversion.',
              'Original ATEM records and source media are unchanged.']
    (out/'ATEM Review.json').write_text(json.dumps(report, indent=2))
    (out/'ATEM Review.txt').write_text('\n'.join(lines)+'\n')
    return str(out/'ATEM Review.txt')
