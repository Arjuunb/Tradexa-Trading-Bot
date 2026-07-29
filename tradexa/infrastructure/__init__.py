"""Infrastructure — implementations of the ports declared in ``tradexa.core``.

This layer may import anything: sockets, databases, exchange SDKs, clocks.
The dependency arrow points inward only — infrastructure knows about the
domain, the domain never knows about infrastructure.
"""
