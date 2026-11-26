"""业务路由汇总：版本历史接口先于通用资源路由注册，再按模块 key 分派。"""
from __future__ import annotations

from app.routers import resource, versioning

ROUTERS = [versioning, resource]
