from dataclasses import dataclass, field
# from abc import ABC
from typing import Dict, List, Optional
# -----------------------------
# Data Models
# -----------------------------]
@dataclass
class Order:
    oid: int = 0.0
    limit: float = 0.0
    size: float = 0.0
    remain_size: float = 0.0
    timestamp:int = 0
    side: str = ""
    action: str = ""

    # is_buy: bool

@dataclass
class Position:
    position_value: float = 0.0
    size: float = 0.0
    entry: float = 0.0
    is_long: bool = None
    leverage: int = 1
    is_mod: bool = False
    unpnl: float = 0.0
    tp : Order = None
    sl : Order = None
    buy_order: List[Order] = field(default_factory=list)
    sell_order: List[Order] = field(default_factory=list)
    market:    List[Order] = field(default_factory=list)

@dataclass
class Trader:
    name : str = None
    address: str = None
    pnl: float = None
    positions: Dict[str, Position] = field(default_factory=dict)
    roi: float = None

@dataclass
class FillEvent:
    closedPnl: float
    coin: str
    crossed: bool
    direction: str
    hash: str
    oid: int
    price: float
    side: str
    start_position: float
    size: float
    time: int
    fee: float
    fee_token: str
    builder_fee: float
    tid: int
#     tid: int = 0
#     coin: str = None
#     volume_percent: float = 0.0 
#     fill_price: float = 0.0
#     pnl : float = 0.0
#     trader_addr: str = ""
#     trader_name: str = ""
#     # trader: Trader = None
#     timestamp: int = 0
#     action: str = None
#     is_market: bool = False


# @dataclass(frozen=True)
# class AllPositionPair:
#     coin : str
#     buy_list: List[Position]
#     sell_list: List[Position]



# @dataclass(frozen=True)
# class PositionLongLimit(Position):

# @dataclass(frozen=True)
# class PositionShortLimit(Position):

