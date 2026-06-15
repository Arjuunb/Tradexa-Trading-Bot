"""Live event streaming for the dashboard (Server-Sent Events).

A process-wide ``HubEventHub`` aggregates events from every live bot runner
(each runner has its own EventBus) and fans them out to connected browsers.
Stdlib only: ``queue`` + ``threading``; the SSE endpoint in ``app.py`` reads a
per-connection queue. Mirrors the pattern in ``bot.dashboard`` but hub-wide.
"""
from __future__ import annotations

import json
import queue
import threading
from collections import deque
from typing import Deque


class HubEventHub:
    def __init__(self, history: int = 2000):
        self._subs: list[queue.Queue] = []
        self._history: Deque[dict] = deque(maxlen=history)
        self._lock = threading.Lock()

    def publish(self, event: dict) -> None:
        with self._lock:
            self._history.append(event)
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait(event)
            except queue.Full:           # slow client: drop oldest, keep newest
                try:
                    q.get_nowait()
                    q.put_nowait(event)
                except queue.Empty:
                    pass

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=1000)
        with self._lock:
            self._subs.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)

    def replay(self) -> list[dict]:
        with self._lock:
            return list(self._history)

    def forward_from(self, bus, bot_id: str, bot_name: str) -> None:
        """Subscribe to a runner's EventBus and re-publish tagged with the bot."""
        def _fwd(event: dict) -> None:
            tagged = dict(event)
            tagged["bot_id"] = bot_id
            tagged["bot_name"] = bot_name
            self.publish(tagged)
        bus.subscribe(_fwd)


def sse_format(event: dict) -> str:
    return f"data: {json.dumps(event, default=str)}\n\n"


# Client script injected into the overview page: connects to /events/stream and
# updates a live feed + a connection indicator without a full-page refresh.
LIVE_FEED_CARD = """
<div class="card"><h2>Live Feed <span id="livestatus" class="muted">connecting…</span></h2>
<div id="livefeed" class="logbox" style="max-height:240px;overflow-y:auto;
font-family:ui-monospace,Menlo,monospace;font-size:11px;line-height:1.7;
background:#0d1117;border:1px solid #1e2733;border-radius:6px;padding:8px 10px">
<div class="dim">Waiting for live bot activity… start a bot with “Go Live”.</div>
</div></div>
<script>
(function(){
  var feed=document.getElementById('livefeed'), status=document.getElementById('livestatus');
  function line(ev){
    var t=ev.type, b=ev.bot_name||'', msg='';
    if(t==='bar'){return;}
    if(t==='signal'){msg='SIGNAL '+(ev.side||'').toUpperCase()+' '+(ev.symbol||'');}
    else if(t==='order'){msg='ORDER '+(ev.side||'').toUpperCase()+' '+(ev.symbol||'');}
    else if(t==='fill'){msg='FILL '+(ev.role||'')+' '+(ev.symbol||'')+' @ '+(ev.price||0);}
    else if(t==='trade_closed'){msg='TRADE '+(ev.symbol||'')+' PnL '+(ev.pnl||0).toFixed(2);}
    else if(t==='risk_block'){msg='RISK BLOCK '+(ev.reason||'');}
    else if(t==='run_finished'){msg='RUN FINISHED';}
    else if(t==='lifecycle'){msg=ev.message||'';}
    else {return;}
    var d=document.createElement('div');
    d.textContent='['+b+'] '+msg;
    if(feed.firstChild && feed.firstChild.className==='dim'){feed.innerHTML='';}
    feed.insertBefore(d, feed.firstChild);
    while(feed.childElementCount>120){feed.removeChild(feed.lastChild);}
  }
  fetch('/events/state').then(function(r){return r.json();}).then(function(s){
    (s.events||[]).slice(-60).forEach(line);
  }).catch(function(){});
  try{
    var src=new EventSource('/events/stream');
    src.onopen=function(){status.textContent='live';};
    src.onerror=function(){status.textContent='disconnected';};
    src.onmessage=function(m){try{line(JSON.parse(m.data));}catch(e){}};
  }catch(e){status.textContent='unsupported';}
})();
</script>
"""
