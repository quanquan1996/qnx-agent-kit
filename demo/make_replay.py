"""Build replay.html from the real run2 transcript (no invented steps)."""
import json, re, sys, html
RUN = '../agent-run/run2/run2.jsonl'
REPO = sys.argv[1] if len(sys.argv) > 1 else 'github.com/<repo-after-approval>'
ev = []  # (kind, text)
def short_res(name, txt):
    try: d = json.loads(txt)
    except Exception: return txt[:300]
    if name.endswith('qnx_run'):
        return '\n'.join(l for l in d['output'].splitlines() if l.startswith('RESULT') or l.strip()=='2')
    if name.endswith('qnx_trace'):
        s = d['summary']; out = [l for l in d['program_output'].splitlines() if l.startswith('RESULT')]
        rp = {k: v for k, v in s['runs_per_thread'] if any(n in k for n in ('control','logger','uploader'))}
        bp = {k: v for k, v in s['blocks_per_thread'] if any(n in k for n in ('control','logger','uploader'))}
        out.append('runs:   ' + ', '.join(f'{k.split(" ")[-1]} {v}' for k, v in rp.items()))
        out.append('blocks: ' + ', '.join(f'{k.split(":")[1].split(" ")[0]} {k.split(" ")[-1]} {v}' for k, v in bp.items()))
        out.append(f'({d["events_lines"]} kernel events decoded)')
        return '\n'.join(out)
    return json.dumps({k: d[k] for k in ('exit_code','seconds') if k in d})
names = {}
for line in open(RUN):
    d = json.loads(line); m = d.get('message')
    if not isinstance(m, dict) or not isinstance(m.get('content'), list): continue
    for x in m['content']:
        t = x.get('type')
        if t == 'text' and not x['text'].startswith('# rt-loop'):
            ev.append(('say', x['text']))
        elif t == 'tool_use':
            names[x['id']] = x['name']; n = x['name'].replace('mcp__qnx__', '')
            if n in ('Glob', 'ToolSearch'): continue
            inp = x['input']
            if n == 'Read': ev.append(('tool', f'Read {inp["file_path"].split("agent-run/")[-1]}'))
            elif n == 'Edit': ev.append(('diff', '- ' + inp['old_string'].replace('\n', '\n- ') + '\n+ ' + inp['new_string'].replace('\n', '\n+ ')))
            else: ev.append(('tool', n + ' ' + json.dumps(inp)))
        elif t == 'tool_result':
            n = names.get(x['tool_use_id'], '')
            if n.startswith('mcp__qnx__') and isinstance(x.get('content'), list):
                ev.append(('out', short_res(n, x['content'][0]['text'])))
    if d.get('type') == 'result': pass
report = [json.loads(l) for l in open(RUN) if '"type": "result"' in l or '"type":"result"' in l]
final = report[-1]['result'] if report else ''
tmpl = open('replay_template.html').read()
out = tmpl.replace('__EVENTS__', json.dumps(ev)).replace('__REPORT__', json.dumps(final)).replace('__REPO__', html.escape(REPO))
open('replay.html', 'w').write(out)
print(len(ev), 'events')
