#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from pathlib import Path
import json, random, string, time, uuid, mimetypes, traceback

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
ROOMS = {}
RANKS = ["3","4","5","6","7","8","9","10","J","Q","K","A","2"]
ORDER = {r:i+3 for i,r in enumerate(RANKS)}
SUITS = [
    {"key":"S", "symbol":"♠", "name":"黑桃", "red":False},
    {"key":"H", "symbol":"♥", "name":"红桃", "red":True},
    {"key":"C", "symbol":"♣", "name":"梅花", "red":False},
    {"key":"D", "symbol":"♦", "name":"方片", "red":True},
]

def room_code():
    while True:
        code = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(5))
        if code not in ROOMS:
            return code

def build_deck():
    deck = []
    for r in RANKS:
        for s in SUITS:
            is_red_ten = (r == "10" and s["red"])
            deck.append({
                "id": f'{s["key"]}{r}', "rank": r, "suit": s["key"], "suitSymbol": s["symbol"],
                "suitName": s["name"], "red": s["red"], "isRedTen": is_red_ten, "isJoker": False,
                "joker": None, "label": "红10" if is_red_ten else r, "sortValue": 18 if is_red_ten else ORDER[r],
                "normalValue": None if is_red_ten else ORDER[r], "normalKey": None if is_red_ten else r,
            })
    deck.append({"id":"SJ","rank":"小王","suit":"","suitSymbol":"☆","suitName":"","red":False,"isRedTen":False,"isJoker":True,"joker":"small","label":"小王","sortValue":16,"normalValue":None,"normalKey":None})
    deck.append({"id":"BJ","rank":"大王","suit":"","suitSymbol":"★","suitName":"","red":False,"isRedTen":False,"isJoker":True,"joker":"big","label":"大王","sortValue":17,"normalValue":None,"normalKey":None})
    return deck

def sort_hand(hand):
    hand.sort(key=lambda c: (c["sortValue"], c.get("suit","")))

def normal_counts(cards):
    m = {}
    for c in cards:
        k = c.get("normalKey")
        if k:
            m[k] = m.get(k, 0) + 1
    return m

def has_triple(hand):
    return any(v >= 3 for v in normal_counts(hand).values())

def has_bomb(hand):
    return any(v >= 4 for v in normal_counts(hand).values())

def has_joker_bomb(hand):
    ids = {c["id"] for c in hand}
    return "SJ" in ids and "BJ" in ids

def is_consecutive(vals):
    return all(vals[i] == vals[i-1] + 1 for i in range(1, len(vals)))

def values_to_ranks(vals):
    rev = {v:k for k,v in ORDER.items()}
    return [rev[v] for v in vals]

def detect_play(cards):
    if not cards:
        return {"ok":False, "reason":"未选择牌"}
    n = len(cards)
    ids = [c["id"] for c in cards]
    red_ten_count = sum(1 for c in cards if c.get("isRedTen"))
    if n == 2 and red_ten_count == 2:
        return {"ok":True, "type":"redTenPair", "rank":1000, "power":1000, "label":"双红十", "cards":cards}
    if n == 2 and "SJ" in ids and "BJ" in ids:
        return {"ok":True, "type":"jokerBomb", "rank":900, "power":900, "label":"双王", "cards":cards}
    if n == 1:
        c = cards[0]
        lab = "红10" if c.get("isRedTen") else c["rank"]
        return {"ok":True, "type":"single", "rank":c["sortValue"], "power":c["sortValue"], "label":f"单张 {lab}", "cards":cards}
    normal = all(c.get("normalKey") for c in cards)
    counts = normal_counts(cards)
    keys = list(counts.keys())
    if normal:
        if n == 2 and len(keys) == 1 and counts[keys[0]] == 2:
            return {"ok":True, "type":"pair", "rank":ORDER[keys[0]], "power":ORDER[keys[0]], "label":f"对子 {keys[0]}", "cards":cards}
        if n == 3 and len(keys) == 1 and counts[keys[0]] == 3:
            return {"ok":True, "type":"triple", "rank":ORDER[keys[0]], "power":100 + ORDER[keys[0]], "label":f"炮 {keys[0]}", "cards":cards}
        if n == 4 and len(keys) == 1 and counts[keys[0]] == 4:
            return {"ok":True, "type":"bomb", "rank":ORDER[keys[0]], "power":200 + ORDER[keys[0]], "label":f"炸 {keys[0]}", "cards":cards}
        vals = sorted([c["normalValue"] for c in cards])
        unique = sorted(set(vals))
        if n >= 3 and len(unique) == n and all(3 <= v <= 14 for v in vals) and is_consecutive(unique):
            return {"ok":True, "type":"straight", "rank":max(vals), "length":n, "power":50 + max(vals), "label":"顺子 " + ''.join(values_to_ranks(unique)), "cards":cards}
        if n >= 6 and n % 2 == 0:
            pair_vals = sorted([ORDER[k] for k in keys])
            all_pairs = all(counts[k] == 2 for k in keys)
            if all_pairs and len(pair_vals) >= 3 and all(3 <= v <= 14 for v in pair_vals) and is_consecutive(pair_vals):
                label = "连队 " + ''.join([x+x for x in values_to_ranks(pair_vals)])
                return {"ok":True, "type":"pairSeq", "rank":max(pair_vals), "length":len(pair_vals), "power":80 + max(pair_vals), "label":label, "cards":cards}
    return {"ok":False, "reason":"不符合当前已实现的牌型"}

def can_beat(play, current):
    if not play or not play.get("ok"):
        return False
    if not current:
        return True
    if play["type"] == "redTenPair": return current["type"] != "redTenPair"
    if current["type"] == "redTenPair": return False
    if play["type"] == "jokerBomb": return current["type"] != "jokerBomb"
    if current["type"] == "jokerBomb": return False
    if play["type"] == "bomb":
        return play["rank"] > current["rank"] if current["type"] == "bomb" else True
    if current["type"] == "bomb": return False
    if current["type"] == "pairSeq" or play["type"] == "pairSeq": return False
    if play["type"] == "triple" and current["type"] in ("single", "pair"): return True
    if current["type"] == "single" and play["type"] == "single": return play["rank"] > current["rank"]
    if current["type"] == "pair" and play["type"] == "pair": return play["rank"] > current["rank"]
    if current["type"] == "triple" and play["type"] == "triple": return play["rank"] > current["rank"]
    if current["type"] == "straight" and play["type"] == "straight" and play.get("length") == current.get("length"):
        return play["rank"] > current["rank"]
    return False

def public_card(c):
    keys = ["id","rank","suit","suitSymbol","suitName","red","isRedTen","isJoker","joker","label","sortValue","normalValue","normalKey"]
    return {k:c[k] for k in keys if k in c}

def new_room(host_name):
    code = room_code(); pid = str(uuid.uuid4())
    room = {"code":code,"created":time.time(),"host":pid,"players":[{"pid":pid,"name":host_name or "玩家1","slot":0,"joined":time.time()}],"handNo":0,"nextDealer":0,"totalScores":[0,0,0,0,0,0],"game":None,"logs":[f"房间 {code} 已创建。等待 6 名玩家加入。"],"suspects":{pid:{}}}
    ROOMS[code] = room
    return room, pid

def add_player(room, name):
    if len(room["players"]) >= 6: raise ValueError("房间已满")
    if room["game"] and room["game"].get("phase") not in ("waiting", "end"): raise ValueError("本局已经开始，不能中途加入")
    used = {p["slot"] for p in room["players"]}; slot = next(i for i in range(6) if i not in used)
    pid = str(uuid.uuid4())
    room["players"].append({"pid":pid,"name":name or f"玩家{slot+1}","slot":slot,"joined":time.time()})
    room["players"].sort(key=lambda p:p["slot"]); room["suspects"][pid] = {}
    room["logs"].append(f"{name or f'玩家{slot+1}'} 加入房间。")
    return pid, slot

def get_player(room, pid):
    for p in room["players"]:
        if p["pid"] == pid: return p
    return None

def start_hand(room):
    if len(room["players"]) != 6: raise ValueError("必须 6 名玩家全部加入后才能开始")
    room["handNo"] += 1; dealer = room.get("nextDealer", 0)
    deck = build_deck(); random.shuffle(deck)
    pid_by_slot = {p["slot"]:p["pid"] for p in room["players"]}; name_by_slot = {p["slot"]:p["name"] for p in room["players"]}
    players_state = [{"slot":i,"pid":pid_by_slot[i],"name":name_by_slot[i],"hand":[],"finished":False,"declare":None} for i in range(6)]
    for i, card in enumerate(deck): players_state[(dealer+i)%6]["hand"].append(card)
    for p in players_state: sort_hand(p["hand"])
    red_players = [p["slot"] for p in players_state if any(c["isRedTen"] for c in p["hand"])]
    h3_holder = next(p["slot"] for p in players_state if any(c["id"] == "H3" for c in p["hand"]))
    room["game"] = {"players":players_state,"redPlayers":red_players,"allRevealed":False,"revealedPlayers":[],"multiplier":1,"phase":"speech","speechOrder":[(dealer+i)%6 for i in range(6)],"speechPos":0,"current":None,"currentPlayer":None,"passes":0,"turn":None,"h3Holder":h3_holder,"firstPlay":True,"finishOrder":[],"dealer":dealer,"gameOver":False,"lastSeq":time.time()}
    room["logs"] = [f"第 {room['handNo']} 局开始。玩家{dealer+1} 先发牌、先说话。"]

def finish_speech(room):
    g = room["game"]; decls = [p["declare"] for p in g["players"]]
    pao = sum(1 for x in decls if x == "有炮"); zha = sum(1 for x in decls if x == "有炸"); wang = sum(1 for x in decls if x == "双王"); red = sum(1 for x in decls if x == "红十")
    if red >= 1 or pao >= 2 or zha >= 1 or wang >= 1:
        g["allRevealed"] = True; g["revealedPlayers"] = list(g["redPlayers"]); g["multiplier"] = 2
        names = "、".join([g["players"][i]["name"] for i in g["redPlayers"]])
        room["logs"].append(f"红十身份被公开，本局底分翻倍。红十阵营：{names}")
    else:
        room["logs"].append("未公开红十身份，本局暗打。")
    g["phase"] = "play"; g["turn"] = g["h3Holder"]
    room["logs"].append(f"红桃3在 {g['players'][g['turn']]['name']} 手中，由其先出。")

def next_active(g, from_slot):
    for step in range(1, 7):
        idx = (from_slot + step) % 6
        if not g["players"][idx]["finished"]: return idx
    return None

def active_count(g): return sum(1 for p in g["players"] if not p["finished"])

def check_auto_end(room):
    g = room["game"]; remaining = [p for p in g["players"] if not p["finished"]]
    if len(remaining) == 1 and not g["gameOver"]:
        remaining[0]["finished"] = True; g["finishOrder"].append(remaining[0]["slot"]); room["logs"].append(f"{remaining[0]['name']} 最后一名。")
        end_game(room)

def calculate_result(room):
    g = room["game"]; order = g["finishOrder"]; first, last = order[0], order[-1]
    red_set = set(g["redPlayers"]); red_positions = sorted([pos+1 for pos, slot in enumerate(order) if slot in red_set])
    first_is_red = first in red_set; last_is_red = last in red_set
    winner, unit, reason = "平局", 0, ""
    if first_is_red and not last_is_red:
        winner = "红十"
        if len(red_positions) == 1: unit, reason = 4, "同一玩家持双红十并第1名出完。"
        else:
            second_red = red_positions[1]; unit = max(0, 6-second_red); reason = f"红十第1名和第{second_red}名出完。"
    elif (not first_is_red) and last_is_red:
        winner = "平民"
        if len(red_positions) == 1: unit, reason = 4, "持双红十玩家最后出完，平民抓住双红十。"
        else:
            caught_both = 5 in red_positions and 6 in red_positions
            unit = 4 if caught_both else 2; reason = "两个红十为最后两名，平民抓住两个红十。" if caught_both else "一个红十最后出完，平民抓住一个红十。"
    else:
        reason = "同一阵营同时占据第1名和最后1名。"
    unit *= g["multiplier"]; scores = [0]*6
    if unit > 0:
        reds = g["redPlayers"]; civs = [i for i in range(6) if i not in red_set]
        if winner == "红十":
            for r in reds: scores[r] += unit * len(civs)
            for c in civs: scores[c] -= unit * len(reds)
        elif winner == "平民":
            for c in civs: scores[c] += unit * len(reds)
            for r in reds: scores[r] -= unit * len(civs)
    return {"winner":winner,"unit":unit,"reason":reason,"scores":scores}

def end_game(room):
    g = room["game"]; g["gameOver"] = True; g["phase"] = "end"; g["allRevealed"] = True; g["revealedPlayers"] = list(g["redPlayers"])
    result = calculate_result(room); g["result"] = result
    for i, s in enumerate(result["scores"]): room["totalScores"][i] += s
    room["nextDealer"] = g["finishOrder"][0]
    room["logs"].append(f"本局结束：{result['winner']}。{result['reason']} 单位分：{result['unit']}")
    room["logs"].append(f"下局由 玩家{room['nextDealer']+1} 先发牌、先说话。")

def public_state(room, pid):
    viewer = get_player(room, pid)
    if not viewer: raise ValueError("玩家不存在")
    viewer_slot = viewer["slot"]; g = room["game"]
    state = {"room":room["code"],"host":room["host"],"you":{"pid":pid,"slot":viewer_slot,"name":viewer["name"]},"players":[],"handNo":room["handNo"],"totalScores":room["totalScores"],"logs":room["logs"][-80:],"suspects":room["suspects"].get(pid, {}),"waiting":g is None}
    if not g:
        state["players"] = [{"slot":p["slot"],"name":p["name"],"joined":True} for p in room["players"]]
        return state
    red_set = set(g["redPlayers"])
    for p in g["players"]:
        slot = p["slot"]; role = None; roleKnown = False
        if slot == viewer_slot or g["allRevealed"] or slot in g["revealedPlayers"] or g["phase"] == "end":
            role = "红十" if slot in red_set else "平民"; roleKnown = True
        state["players"].append({"slot":slot,"name":p["name"],"cardCount":len(p["hand"]),"finished":p["finished"],"declare":p["declare"],"roleKnown":roleKnown,"role":role,"finishRank":(g["finishOrder"].index(slot)+1) if slot in g["finishOrder"] else None})
    me = g["players"][viewer_slot]
    state.update({"phase":g["phase"],"speechCurrent":g["speechOrder"][g["speechPos"]] if g["phase"] == "speech" and g["speechPos"] < 6 else None,"turn":g["turn"],"dealer":g["dealer"],"firstPlay":g["firstPlay"],"current":None if not g["current"] else {"type":g["current"]["type"],"label":g["current"]["label"],"rank":g["current"]["rank"],"length":g["current"].get("length"),"cards":[public_card(c) for c in g["current"]["cards"]]},"currentPlayer":g["currentPlayer"],"multiplier":g["multiplier"],"allRevealed":g["allRevealed"],"revealedPlayers":g["revealedPlayers"],"finishOrder":g["finishOrder"],"result":g.get("result"),"ownHand":[public_card(c) for c in me["hand"]]})
    return state

def action_declare(room, pid, data):
    g = room["game"]; viewer = get_player(room, pid)
    if not g or g["phase"] != "speech": raise ValueError("当前不是说话阶段")
    slot = viewer["slot"]; current_slot = g["speechOrder"][g["speechPos"]]
    if slot != current_slot: raise ValueError("还没轮到你说话")
    text = data.get("declare")
    if text not in ["没话","有炮","有炸","双王","红十"]: raise ValueError("无效说话内容")
    p = g["players"][slot]
    if text == "红十" and slot not in g["redPlayers"]: raise ValueError("你不是红十，不能亮红十")
    if text == "有炮" and not has_triple(p["hand"]): raise ValueError("你没有炮，不能报有炮")
    if text == "有炸" and not has_bomb(p["hand"]): raise ValueError("你没有炸，不能报有炸")
    if text == "双王" and not has_joker_bomb(p["hand"]): raise ValueError("你没有双王")
    p["declare"] = text
    if text == "红十" and slot not in g["revealedPlayers"]: g["revealedPlayers"].append(slot)
    room["logs"].append(f"{p['name']}：{text}")
    g["speechPos"] += 1
    if g["speechPos"] >= 6: finish_speech(room)

def action_suspect(room, pid, data):
    target = int(data.get("target")); mark = data.get("mark")
    if target < 0 or target > 5: raise ValueError("目标玩家无效")
    if mark not in ["未知","怀疑红十","认为平民"]: raise ValueError("标记无效")
    room["suspects"].setdefault(pid, {})
    if mark == "未知": room["suspects"][pid].pop(str(target), None)
    else: room["suspects"][pid][str(target)] = mark

def action_play(room, pid, data):
    g = room["game"]; viewer = get_player(room, pid)
    if not g or g["phase"] != "play": raise ValueError("当前不是出牌阶段")
    slot = viewer["slot"]
    if g["turn"] != slot: raise ValueError("还没轮到你出牌")
    p = g["players"][slot]; ids = set(data.get("cards") or [])
    if not ids: raise ValueError("未选择牌")
    cards = [c for c in p["hand"] if c["id"] in ids]
    if len(cards) != len(ids): raise ValueError("选牌不在你的手牌中")
    play = detect_play(cards)
    if not play["ok"]: raise ValueError(play["reason"])
    if g["firstPlay"] and not any(c["id"] == "H3" for c in cards): raise ValueError("第一手必须包含红桃3")
    if not can_beat(play, g["current"]): raise ValueError("这手牌不能压过桌面")
    # 出牌阶段打出红十：只公开该玩家身份，不触发翻倍。
    # 翻倍只由说话环节“亮红十/两炮/一炸/双王”等公开身份条件触发。
    if any(c.get("isRedTen") for c in cards) and slot not in g["revealedPlayers"]:
        g["revealedPlayers"].append(slot); room["logs"].append(f"{p['name']} 打出了红十，身份自动标记为红十。")
    remove = set(ids); p["hand"] = [c for c in p["hand"] if c["id"] not in remove]; sort_hand(p["hand"])
    g["current"] = {k:v for k,v in play.items() if k != "ok"}; g["currentPlayer"] = slot; g["passes"] = 0; g["firstPlay"] = False
    room["logs"].append(f"{p['name']} 出：{play['label']}")
    if len(p["hand"]) == 0 and not p["finished"]:
        p["finished"] = True; g["finishOrder"].append(slot); room["logs"].append(f"{p['name']} 第 {len(g['finishOrder'])} 名出完。")
    check_auto_end(room)
    if not g["gameOver"]: g["turn"] = next_active(g, slot)

def action_pass(room, pid):
    g = room["game"]; viewer = get_player(room, pid)
    if not g or g["phase"] != "play": raise ValueError("当前不是出牌阶段")
    slot = viewer["slot"]
    if g["turn"] != slot: raise ValueError("还没轮到你")
    if not g["current"]: raise ValueError("领出时不能不要")
    room["logs"].append(f"{g['players'][slot]['name']}：不要")
    g["passes"] += 1; needed = active_count(g) - 1
    if g["passes"] >= needed:
        last = g["currentPlayer"]; room["logs"].append(f"一圈无人压过，{g['players'][last]['name']} 获得下一轮牌权。")
        g["current"] = None; g["currentPlayer"] = None; g["passes"] = 0
        g["turn"] = next_active(g, last) if g["players"][last]["finished"] else last
    else: g["turn"] = next_active(g, slot)

def handle_action(room, pid, payload):
    typ = payload.get("type"); data = payload.get("data") or {}
    if typ == "start":
        if pid != room["host"]: raise ValueError("只有房主可以开始")
        start_hand(room)
    elif typ == "new_hand":
        g = room.get("game")
        if g and g["phase"] != "end": raise ValueError("本局尚未结束")
        start_hand(room)
    elif typ == "declare": action_declare(room, pid, data)
    elif typ == "play": action_play(room, pid, data)
    elif typ == "pass": action_pass(room, pid)
    elif typ == "suspect": action_suspect(room, pid, data)
    else: raise ValueError("未知操作")
    if room.get("game"): room["game"]["lastSeq"] = time.time()

class Handler(BaseHTTPRequestHandler):
    server_version = "HongShiRoom/0.3.1"
    def send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(body))); self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(body)
    def read_json(self):
        n = int(self.headers.get("Content-Length", 0)); raw = self.rfile.read(n).decode("utf-8") if n else "{}"; return json.loads(raw or "{}")
    def do_GET(self):
        try:
            parsed = urlparse(self.path)
            if parsed.path == "/api/state":
                qs = parse_qs(parsed.query); code = (qs.get("room") or [""])[0].upper(); pid = (qs.get("pid") or [""])[0]
                room = ROOMS.get(code)
                if not room: self.send_json({"ok":False,"error":"房间不存在"}, 404); return
                self.send_json({"ok":True,"state":public_state(room, pid)}); return
            path = "/index.html" if parsed.path == "/" else parsed.path
            f = (WEB / path.lstrip("/")).resolve()
            if not str(f).startswith(str(WEB.resolve())) or not f.exists() or f.is_dir(): self.send_error(404); return
            ctype = mimetypes.guess_type(str(f))[0] or "application/octet-stream"; data = f.read_bytes()
            self.send_response(200); self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith("text/") else "")); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
        except Exception as e:
            traceback.print_exc(); self.send_json({"ok":False,"error":str(e)}, 500)
    def do_POST(self):
        try:
            parsed = urlparse(self.path); payload = self.read_json()
            if parsed.path == "/api/create":
                room, pid = new_room(payload.get("name") or "玩家1"); self.send_json({"ok":True,"room":room["code"],"pid":pid,"slot":0}); return
            if parsed.path == "/api/join":
                code = (payload.get("room") or "").upper(); room = ROOMS.get(code)
                if not room: self.send_json({"ok":False,"error":"房间不存在"}, 404); return
                pid, slot = add_player(room, payload.get("name") or f"玩家{len(room['players'])+1}"); self.send_json({"ok":True,"room":code,"pid":pid,"slot":slot}); return
            if parsed.path == "/api/action":
                code = (payload.get("room") or "").upper(); pid = payload.get("pid") or ""; room = ROOMS.get(code)
                if not room: self.send_json({"ok":False,"error":"房间不存在"}, 404); return
                if not get_player(room, pid): self.send_json({"ok":False,"error":"玩家不存在"}, 403); return
                handle_action(room, pid, payload); self.send_json({"ok":True}); return
            self.send_error(404)
        except Exception as e: self.send_json({"ok":False,"error":str(e)}, 400)
    def log_message(self, fmt, *args): print("[%s] %s" % (self.log_date_time_string(), fmt % args))

if __name__ == "__main__":
    print("红十多人房间版 v3.1 已启动")
    print("本机打开：http://127.0.0.1:8000")
    print("局域网玩家打开：http://你的电脑IP:8000")
    ThreadingHTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
