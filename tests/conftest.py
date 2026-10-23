# -*- coding: utf-8 -*-
"""飞划APS · 测试夹具：临时库 + 随机空闲端口 + 真实 HTTP 服务"""
import json
import os
import socket
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

TMP = tempfile.mkdtemp(prefix="aps_test_")
os.environ["APS_DB"] = os.path.join(TMP, "test.db")
os.environ["APS_PREFIX"] = ""
if "APS_PORT" in os.environ:
    del os.environ["APS_PORT"]

import pytest  # noqa: E402

import db  # noqa: E402
import seed as seedmod  # noqa: E402


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture(scope="session")
def server():
    db.init()
    seedmod.seed()
    import server as srvmod
    port = _free_port()
    srvmod.PORT = port
    from http.server import ThreadingHTTPServer
    httpd = ThreadingHTTPServer(("127.0.0.1", port), srvmod.Handler)
    th = threading.Thread(target=httpd.serve_forever, daemon=True)
    th.start()
    yield "http://127.0.0.1:%d" % port
    httpd.shutdown()
    db.close_thread_conns()


import threading  # noqa: E402


class Client(object):
    def __init__(self, base, username=None, password=None):
        self.base = base
        self.token = ""
        self.user = username or ""
        self.password = password or ""
        self._logins = 0

    def _req(self, method, path, body=None, headers=None, raw=False):
        url = self.base + urllib.parse.quote(path, safe="/?:=&%+,.[]{}")
        data = json.dumps(body).encode("utf-8") if method == "POST" and body is not None else \
            (body.encode("utf-8") if method == "POST" and isinstance(body, str) else None)
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if self.token:
            req.add_header("Authorization", "Bearer " + self.token)
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                payload = resp.read()
                return resp.status, payload if raw else json.loads(payload.decode("utf-8"))
        except urllib.error.HTTPError as e:
            payload = e.read()
            if raw:
                return e.code, payload
            try:
                return e.code, json.loads(payload.decode("utf-8"))
            except Exception:  # noqa: BLE001
                return e.code, {}

    def call(self, method, path, body=None, no_retry=False, **kw):
        st, j = self._req(method, path, body, **kw)
        if path == "/api/auth/login" and st == 200 and isinstance(j, dict) and j.get("data"):
            self.token = j["data"].get("token", "")
        if st == 401 and self.user and not no_retry and self._logins < 3:
            self.login()
            self._logins += 1
            st, j = self._req(method, path, body, **kw)
        return st, j

    def login(self):
        st, j = self._req("POST", "/api/auth/login",
                          {"username": self.user, "password": self.password})
        assert st == 200, j
        self.token = j["data"]["token"]
        return j["data"]


@pytest.fixture(scope="session")
def admin(server):
    c = Client(server, "admin", "aps@2026")
    c.login()
    return c


@pytest.fixture(scope="session")
def tokens(server):
    out = {}
    for role, user, pw in [("planner", "planner", "plan@2026"), ("sched", "sched", "sched@2026"),
                           ("sales", "sales", "sale@2026"), ("prod", "prod", "prod@2026"),
                           ("reader", "reader", "read@2026")]:
        c = Client(server, user, pw)
        c.login()
        out[role] = c
    return out
