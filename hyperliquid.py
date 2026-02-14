# -----------------------------
# Hyperliquid API Controller (Fixed: Stats Endpoint for Leaderboard)
# -----------------------------
from models import Trader, Position, Order, FillEvent
from typing import List, Dict, Optional, Set, Tuple
import requests
import json
import time
from datetime import datetime, timedelta
from copy import deepcopy
class HyperliquidAPI:
    def __init__(self, config):
        self.cfg = config  
        self.base = "https://api.hyperliquid.xyz"  # Official for fills/positions
        self.stats_base = "https://stats-data.hyperliquid.xyz/Mainnet"  # Leaderboard
        
        

    def _post_info(self, payload: Dict) -> Dict:
        """Official /info POST for fills/positions."""
        headers = {
            'User-Agent': 'Mozilla/5.0 (compatible; Bot)',
            'Content-Type': 'application/json'
        }
        try:
            resp = requests.post(f"{self.base}/info", json=payload, headers=headers, timeout=10)
            if resp.status_code != 200:
                print(f"ERROR: {resp.text[:100]}...")
                return {}
            return resp.json()
        except Exception as e:
            print(f"Request failed: {e}")
            return {}

    def get_leaderboard(self, timeframe: str = "allTime", limit: int = 100) -> List[Trader]:
        """
        Fetch leaderboard from stats endpoint.
        Timeframe: "day", "week", "month", "allTime".
        """
        valid_frames = ["day", "week", "month", "allTime"]
        # self.timefr = timeframe
        if timeframe not in valid_frames:
            timeframe = "allTime"

        url = f"{self.stats_base}/leaderboard"
        try:
            resp = requests.get(url, timeout=20)
            if resp.status_code != 200:
                print(f"ERROR: {resp.text[:100]}...")
                return []

            data = resp.json()
            rows = data.get("leaderboardRows", [])[:]  # oversample
            traders = []

            for row in rows:
                try:
                    address = row.get("ethAddress", "")
                    if not address:
                        continue

                    # performances = row.get("windowPerformances",[])[valid_frames[timeframe]]
                    performances = {tf[0]: tf[1] for tf in row.get("windowPerformances", [])}
                    pnl_data = performances.get(timeframe, {})
                    pnl = float(pnl_data.get("pnl", 0))
                    roi = float(pnl_data.get("roi", 0)) * 100
                    name = row.get("displayName", "")
                    # volume = float(pnl_data.get("vlm", 0))

                    # Apply filters

                    if pnl >= self.cfg.pnl_min and roi >= self.cfg.min_roi:
                        # print(f'allow pnl : {pnl} roi: {roi}') 
                        traders.append(
                            Trader(
                                name=name,
                                address=address,
                                pnl=pnl,
                                positions={},
                                roi=roi
                            )
                        )
                    if len(traders) > limit:
                        break  
                except (KeyError, ValueError, TypeError) as e:
                    print(f"Parse error for {row.get('ethAddress', 'unknown')}: {e}")
                    continue

            # Sort by PnL descending
            print(f'trades len {len(traders)}')
            traders.sort(key=lambda x: x.pnl, reverse=True)
            traders = traders[:limit]
            return traders

        except Exception as e:
            print(f"Stats request failed: {e}")
            return []

    def position_update_local(self, pos:Position, event:FillEvent):
        # start_position + size
        if "Long" in event.direction and "Open" in event.direction:
            # 
            pos.size = event.start_position + event.size 

        if "Long" in event.direction and "Close" in event.direction:
            # 
            pos.size = event.start_position - event.size

        if "Short" in event.direction and "Open" in event.direction:
            
            pos.size = event.start_position - event.size

        if "Short" in event.direction and "Close" in event.direction:

            pos.size = event.start_position + event.size

        pos.unpnl -= int(event.closedPnl)
        if pos.size == 0:
            pos.is_long = None
            pos.leverage = 0
            pos.position_value = 0
            pos.entry = 0
            pos.unpnl = 0
        if pos.size > 0:
            pos.is_long = True
            pos.position_value = event.price*pos.size
        if pos.size < 0:
            pos.is_long = False
            pos.position_value = event.price*pos.size

    def position_update(self, trader: Trader):
        payload = {"type": "clearinghouseState", "user": trader.address}
        data = self._post_info(payload)
        asset_positions = data.get("assetPositions", [])

        for p in asset_positions:
            position = p.get("position")
            if not position:
                continue
            if p.get("type") != "oneWay":
                continue

            position_value = float(position.get("positionValue"))
            entry       = float( position.get("entryPx"))
            leverage    = int(position.get("leverage").get("value"))
            size        = float(position.get("szi"))
            coin        = (position.get("coin"))
            unpnl       = float(position.get("unrealizedPnl"))
            is_buy = False
            if size > 0:
                is_buy = True

            trader.positions[coin] = Position(
                position_value=position_value,
                size=size,
                entry=entry,
                is_long=is_buy,
                leverage=leverage,
                is_mod=True,
                unpnl=unpnl,
            
                buy_order=[],
                sell_order=[],
                market=[]
            )
        

    def load_limit_orders(self, trader: Trader):
        payload = {"type": "frontendOpenOrders", "user": trader.address}
        data = self._post_info(payload)

        for c in trader.positions.keys():
            trader.positions[c].buy_order = []
            trader.positions[c].sell_order = []
            trader.positions[c].market = []

        
        for o in data:
            coin=o.get("coin")
            oid=o.get("oid", 0)
            orig_size=float(o.get("origSz", 0))
            remaining_size=float(o.get("sz", 0))
            timestamp=int(o.get("timestamp", time.time() * 1000))            
            side=o.get("side")
            
            is_trigger=o.get("isTrigger", False)
            is_position_tpsl=o.get("isPositionTpsl", False)

            pos = trader.positions.get(coin, None)
            if pos is None:
                self.position_update(trader)
                pos = trader.positions.get(coin, None)
                if pos is None:
                    trader.positions[coin] = Position(
                        position_value=0.0,
                        size=0.0,
                        entry=0.0,
                        is_long=None,
                        leverage=1,
                        is_mod=True,
                        unpnl=0.0,
                        buy_order=[],
                        sell_order=[],
                        market=[]
                    )
                    pos =  trader.positions[coin]
            
            if is_trigger and is_position_tpsl:                
                trigger_price=float(o.get("triggerPx", 0))

                tpsl_order = Order(
                    limit=trigger_price,
                    size=orig_size,
                    remain_size=remaining_size,
                    timestamp=timestamp,     
                    side=side,
                    action="output"              
                )

                if pos.is_long and pos.entry > trigger_price:
                    pos.sl = tpsl_order
                if pos.is_long and pos.entry < trigger_price:
                    pos.tp = tpsl_order
                if not pos.is_long and pos.entry > trigger_price:
                    pos.tp = tpsl_order
                if not pos.is_long and pos.entry < trigger_price:
                    pos.sl = tpsl_order
                
            else:
                
                order_type=o.get("orderType")
                reduce_only= bool(o.get("reduceOnly", False))
                limit_price=float(o.get("limitPx", 0))

                if order_type == "Limit":
                    limit_order = Order(
                        limit=limit_price,
                        size=orig_size,
                        remain_size=remaining_size,
                        timestamp=timestamp,
                        side=side,
                        action="output" if reduce_only else "input"
                    )
                    if limit_order.side == "B":
                        is_exist = 0
                        for b in pos.buy_order:
                            if b.oid == oid:
                                is_exist=1
                        if is_exist == 0:
                            pos.buy_order.append(limit_order)
                    else:
                        is_exist = 0
                        for s in pos.sell_order:
                            if s.oid == oid:
                                is_exist=1
                        if is_exist == 0:
                            pos.sell_order.append(limit_order)

    def position_fills(self, trader: Trader, last_upd):
        url = "https://api.hyperliquid.xyz/info"
        payload = {
            "type": "userFillsByTime",
            "user": trader.address,
            "startTime": int(last_upd) * 1000, 
            "endTime": int(time.time()) * 1000,
            "aggregateByTime": True
        }

        try:
            resp = requests.post(url, json=payload, timeout=10)
            data = resp.json()
        except Exception as e:
            print(f"Error loading fills for {trader.address}: {e}")
            return []

        if not isinstance(data, list):
            print(f"Unexpected response for {trader.address}: {data}")
            return []
        # print(data)
        events = []

        for item in data:

            # --- фильтр: берем только perp ---
            coin = item.get("coin", "")
            if coin.startswith("@"):
                # это spot, пропускаем
                continue

            try:
                ev = FillEvent(
                    closedPnl=float(item.get("closedPnl", 0.0)),
                    coin=coin,
                    crossed=bool(item.get("crossed", False)),
                    direction=item.get("dir", ""),
                    hash=item.get("hash", ""),
                    oid=int(item.get("oid", 0)),
                    price=float(item.get("px", 0.0)),
                    side=item.get("side", ""), 
                    start_position=float(item.get("startPosition", 0.0)),
                    size=float(item.get("sz", 0.0)),
                    time=int(item.get("time", 0)),
                    fee=float(item.get("fee", 0.0)),
                    fee_token=item.get("feeToken", ""),
                    builder_fee=float(item.get("builderFee", 0.0)) if item.get("builderFee") else 0.0,
                    tid=int(item.get("tid", 0))
                )
                events.append(ev)
            except Exception as e:
                print(f"Error parsing fill: {item} — {e}")

        return events
            

    # def load_position_info(self, trader: Trader):
    #     trader_address = trader.address
    #     payload = {"type":"userFillsByTime", "user":trader_address, "aggregateByTime": True}
    #     data = self._post_info(payload)
    #     events = []
    #     for active_position in data:
    #         coin        = active_position.get("coin")
    #         if '@' in coin:
    #             # skip spot
    #             continue
    #         sz          = float(active_position.get("sz"))
    #         dir         = active_position.get("dir")
    #         tid         = int(active_position.get("tid"))
    #         prev_size   = active_position.get("startPositions")
    #         entry_price = float(active_position.get("px"))
    #         if prev_size is None:
    #             prev_size = 0.0
    #         else:
    #             prev_size = float(prev_size)
    #         pos = trader.positions.get(coin, None)
            

    #         side        = active_position.get("side")
    #         closed_pnl  = float(active_position.get("closedPnl"))
    #         time_event  = int(active_position.get("time"))

    #         action = "input"
            
            
    #         volume_p = 0
    #         if prev_size != 0: volume_p = (sz/prev_size)*100

    #         if pos is None:
    #             # position not created
    #             # print("pos_is new")
                
    #             pos = Position(                    
    #                 tid=tid,
    #                 size = prev_size+sz,
    #                 entry= entry_price,
    #                 is_long = True if dir == "Open Long" else False,
    #                 is_mod=True,
                    
    #             )
    #             if (pos.is_long and side == "A") or (not pos.is_long and side == "B"):
    #                 action="output" 

    #             events.append(
    #                 PositionEvent(
    #                     tid=tid,
    #                     coin=coin,
    #                     volume_percent=volume_p,
    #                     fill_price=entry_price*sz,
    #                     pnl=closed_pnl,
    #                     trader_addr=trader.address,
    #                     trader_name=trader.name,
    #                     timestamp=time_event,
    #                     action=action,
    #                     is_market=True
    #                 )
    #             )

    #             continue
    #         if pos.size == 0:
    #             pos.entry = entry_price

    #         pos.tid = tid
    #         pos.size = prev_size+sz
    #         pos.is_long = False
    #         if dir == "Open Long":
    #             pos.is_long=True

    #         if (pos.is_long and side == "A") or (not pos.is_long and side == "B"):
    #             action="output" 
            
            
    #         events.append(
    #             PositionEvent(
    #                 tid=tid,
    #                 coin=coin,
    #                 volume_percent=volume_p,
    #                 fill_price=entry_price*sz,
    #                 pnl=closed_pnl,
    #                 trader_addr=trader.address,
    #                 trader_name=trader.name,
    #                 timestamp=time_event,
    #                 action=action
    #             )
    #         )
    #     return events
