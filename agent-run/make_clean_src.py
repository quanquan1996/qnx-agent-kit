"""Regenerate rt-loop/rt_loop.c for an agent run: the demo source minus the
USE_MUTEX fix and the comments that give the answer away."""
import re, os
here = os.path.dirname(os.path.abspath(__file__))
s = open(os.path.join(here, '../qnx-agent-kit/demo/rt-loop/rt_loop.c')).read()
s = '''/* rt-loop: 1 kHz control loop (prio 50) sharing state with a logger (prio 10)
 * and an uploader (prio 30). Prints one RESULT line after 5 s. */
''' + s[s.index('#include'):]
s = re.sub(r'#ifdef USE_MUTEX\nstatic pthread_mutex_t.*?#else\n(.*?)#endif\n', r'\1', s, flags=re.S)
s = s.replace('RESULT lock=%s steps', 'RESULT steps')
s = re.sub(r'#ifdef USE_MUTEX\n\s*"mutex",\n#else\n\s*"semaphore",\n#endif\n', '', s)
s = s.replace(' /* logger -> uploader wake-up (a semaphore is right here) */', '')
s = re.sub(r'#if defined\(USE_MUTEX\).*?#endif\n#ifndef USE_MUTEX\n(.*?)#endif\n', r'\1', s, flags=re.S)
s = s.replace('    /* single CPU makes the inversion deterministic; QNX: run with `on -C 1` or set runmask */\n', '')
open(os.path.join(here, 'rt-loop/rt_loop.c'), 'w').write(s)
