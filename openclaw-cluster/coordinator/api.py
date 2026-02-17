"""
OpenClaw 集群系统 - 节点管理 REST API

提供节点管理的HTTP接口，使用FastAPI实现
"""
from typing import List, Optional
from datetime import datetime

from fastapi import FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ConfigDict
from uvicorn import Config as UvicornConfig, Server

from common.models import NodeInfo, NodeStatus
from common.logging import get_logger
from common.config import Config
from storage.database import Database
from storage.repositories import NodeRepository
from coordinator.node_service import NodeRegistrationService
from coordinator.heartbeat_monitor import HeartbeatMonitor

logger = get_logger(__name__)


# ========== Pydantic 模型 ==========


class NodeRegistrationRequest(BaseModel):
    """节点注册请求模型"""
    hostname: str = Field(..., description="主机名")
    platform: str = Field(..., description="平台 (macos/windows/linux)")
    arch: str = Field(..., description="架构 (x64/arm64)")
    available_skills: List[str] = Field(..., description="可用技能列表")
    ip_address: str = Field("", description="IP地址")
    tailscale_ip: str = Field("", description="Tailscale IP")
    port: int = Field(18789, description="服务端口")
    max_concurrent_tasks: int = Field(5, description="最大并发任务数", ge=1, le=100)
    tags: Optional[List[str]] = Field(None, description="节点标签")
    node_id: Optional[str] = Field(None, description="指定节点ID（可选）")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "hostname": "worker-01",
                "platform": "linux",
                "arch": "x64",
                "available_skills": ["python", "data-analysis", "ml"],
                "ip_address": "192.168.1.100",
                "tailscale_ip": "100.100.100.1",
                "port": 18789,
                "max_concurrent_tasks": 5,
                "tags": ["gpu", "high-memory"],
            }
        }
    )


class NodeRegistrationResponse(BaseModel):
    """节点注册响应模型"""
    success: bool = Field(..., description="是否成功")
    node_id: Optional[str] = Field(None, description="节点ID")
    message: str = Field(..., description="响应消息")
    registered: bool = Field(..., description="是否为新注册")
    node_info: Optional[dict] = Field(None, description="节点信息")


class NodeInfoResponse(BaseModel):
    """节点信息响应模型"""
    node_id: str
    hostname: str
    platform: str
    arch: str
    status: str
    available_skills: List[str]
    max_concurrent_tasks: int
    running_tasks: int
    ip_address: str
    tailscale_ip: str
    port: int
    cpu_usage: float
    memory_usage: float
    disk_usage: float
    total_tasks_processed: int
    successful_tasks: int
    failed_tasks: int
    average_execution_time: float
    registered_at: Optional[str]
    last_heartbeat: Optional[str]
    tags: List[str]


class NodeHealthResponse(BaseModel):
    """节点健康状态响应模型"""
    node_id: str
    hostname: Optional[str]
    healthy: bool
    status: str
    last_heartbeat: Optional[str]
    time_since_heartbeat: Optional[float]
    is_timeout: bool
    cpu_usage: float
    memory_usage: float
    disk_usage: float
    running_tasks: int
    max_concurrent_tasks: int
    available_capacity: int


class ClusterHealthResponse(BaseModel):
    """集群健康状态响应模型"""
    checked_at: str
    total_nodes: int
    nodes_by_status: dict
    online_nodes: int
    offline_nodes: int
    busy_nodes: int
    timeout_nodes_count: int
    total_capacity: int
    used_capacity: int
    available_capacity: int
    capacity_utilization: float


class HeartbeatUpdateRequest(BaseModel):
    """心跳更新请求模型"""
    cpu_usage: float = Field(0.0, ge=0, le=100, description="CPU使用率")
    memory_usage: float = Field(0.0, ge=0, le=100, description="内存使用率")
    disk_usage: float = Field(0.0, ge=0, le=100, description="磁盘使用率")
    running_tasks: int = Field(0, ge=0, description="当前运行任务数")


# ========== FastAPI 应用 ==========


def create_api_app(
    node_service: NodeRegistrationService,
    heartbeat_monitor: HeartbeatMonitor,
) -> FastAPI:
    """
    创建FastAPI应用

    Args:
        node_service: 节点注册服务
        heartbeat_monitor: 心跳监控服务

    Returns:
        FastAPI应用实例
    """
    app = FastAPI(
        title="OpenClaw 集群管理 API",
        description="OpenClaw集群系统的节点管理和监控API",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # 配置CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # 生产环境应限制具体域名
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ========== 中间件 ==========

    @app.middleware("http")
    async def log_requests(request, call_next):
        """记录所有请求"""
        start_time = datetime.now()
        response = await call_next(request)
        duration = (datetime.now() - start_time).total_seconds()
        logger.info(
            f"{request.method} {request.url.path} - "
            f"状态: {response.status_code} - 耗时: {duration:.3f}s"
        )
        return response

    # ========== 异常处理 ==========

    @app.exception_handler(Exception)
    async def global_exception_handler(request, exc):
        """全局异常处理"""
        logger.error(f"未处理的异常: {exc}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "success": False,
                "message": "内部服务器错误",
                "detail": str(exc),
            },
        )

    # ========== 健康检查 ==========

    @app.get("/health", tags=["系统"])
    async def health_check():
        """API健康检查"""
        return {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "service": "OpenClaw Coordinator API",
        }

    # ========== 节点注册 ==========

    @app.post(
        "/api/v1/nodes/register",
        response_model=NodeRegistrationResponse,
        tags=["节点管理"],
        summary="注册新节点",
        description="工作节点调用此接口进行注册，获取节点ID",
    )
    async def register_node(request: NodeRegistrationRequest):
        """注册新节点"""
        try:
            result = await node_service.register_node(
                hostname=request.hostname,
                platform=request.platform,
                arch=request.arch,
                available_skills=request.available_skills,
                ip_address=request.ip_address,
                tailscale_ip=request.tailscale_ip,
                port=request.port,
                max_concurrent_tasks=request.max_concurrent_tasks,
                tags=request.tags,
                node_id=request.node_id,
            )

            # 设置正确的HTTP状态码
            status_code = (
                status.HTTP_200_OK
                if result["success"]
                else status.HTTP_400_BAD_REQUEST
            )

            return JSONResponse(content=result, status_code=status_code)

        except Exception as e:
            logger.error(f"节点注册失败: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"节点注册失败: {str(e)}",
            )

    # ========== 节点查询（更具体的路由在前）==========

    @app.get(
        "/api/v1/nodes/online",
        response_model=List[NodeInfoResponse],
        tags=["节点管理"],
        summary="获取在线节点",
        description="获取所有当前在线的节点列表",
    )
    async def get_online_nodes():
        """获取在线节点"""
        try:
            nodes = await node_service.list_online_nodes()
            return [_node_to_response(node) for node in nodes]

        except Exception as e:
            logger.error(f"获取在线节点失败: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"获取在线节点失败: {str(e)}",
            )

    @app.get(
        "/api/v1/nodes/skills/{skill}",
        response_model=List[NodeInfoResponse],
        tags=["节点管理"],
        summary="按技能查找节点",
        description="查找具有特定技能的在线节点",
    )
    async def find_nodes_by_skill(skill: str):
        """按技能查找节点"""
        try:
            nodes = await node_service.find_nodes_by_skill(skill)
            return [_node_to_response(node) for node in nodes]

        except Exception as e:
            logger.error(f"按技能查找节点失败: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"按技能查找节点失败: {str(e)}",
            )

    @app.get(
        "/api/v1/nodes",
        response_model=List[NodeInfoResponse],
        tags=["节点管理"],
        summary="获取所有节点",
        description="获取集群中所有节点的信息列表",
    )
    async def get_nodes(
        status_filter: Optional[str] = Query(
            None, description="按状态过滤: online, offline, busy, maintenance, error"
        )
    ):
        """获取所有节点"""
        try:
            nodes = await node_service.list_all_nodes()

            # 状态过滤
            if status_filter:
                try:
                    filter_status = NodeStatus(status_filter)
                    nodes = [n for n in nodes if n.status == filter_status]
                except ValueError:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"无效的状态值: {status_filter}",
                    )

            # 转换为响应模型
            return [_node_to_response(node) for node in nodes]

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"获取节点列表失败: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"获取节点列表失败: {str(e)}",
            )

    @app.get(
        "/api/v1/nodes/{node_id}",
        response_model=NodeInfoResponse,
        tags=["节点管理"],
        summary="获取节点详情",
        description="根据节点ID获取节点的详细信息",
    )
    async def get_node(node_id: str):
        """获取节点详情"""
        try:
            node = await node_service.get_node(node_id)
            if not node:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"节点不存在: {node_id}",
                )

            return _node_to_response(node)

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"获取节点详情失败: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"获取节点详情失败: {str(e)}",
            )

    # ========== 节点操作（更具体的路由在前）==========

    @app.post(
        "/api/v1/nodes/{node_id}/shutdown",
        tags=["节点管理"],
        summary="关闭节点",
        description="将节点标记为离线状态（优雅关闭）",
    )
    async def shutdown_node(node_id: str):
        """关闭节点"""
        try:
            success = await node_service.unregister_node(node_id)
            if not success:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"节点不存在或关闭失败: {node_id}",
                )

            return {
                "success": True,
                "message": f"节点 {node_id} 已标记为离线",
                "node_id": node_id,
            }

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"关闭节点失败: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"关闭节点失败: {str(e)}",
            )

    @app.post(
        "/api/v1/nodes/{node_id}/heartbeat",
        tags=["节点管理"],
        summary="更新节点心跳",
        description="节点定期调用此接口更新心跳信息",
    )
    async def update_heartbeat(node_id: str, request: HeartbeatUpdateRequest):
        """更新节点心跳"""
        try:
            success = await heartbeat_monitor.update_node_heartbeat(
                node_id=node_id,
                cpu_usage=request.cpu_usage,
                memory_usage=request.memory_usage,
                disk_usage=request.disk_usage,
                running_tasks=request.running_tasks,
            )

            if not success:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"节点不存在: {node_id}",
                )

            return {
                "success": True,
                "message": "心跳更新成功",
                "node_id": node_id,
                "timestamp": datetime.now().isoformat(),
            }

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"更新心跳失败: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"更新心跳失败: {str(e)}",
            )

    # ========== 健康状态查询（更具体的路由在前）==========

    @app.get(
        "/api/v1/nodes/{node_id}/health",
        tags=["监控"],
        summary="获取节点健康状态",
        description="获取指定节点的健康状态信息",
    )
    async def get_node_health(node_id: str):
        """获取节点健康状态"""
        try:
            health = await heartbeat_monitor.get_node_health_status(node_id)
            # 如果节点不存在，返回404
            if health.get("status") == "not_found":
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"节点不存在: {node_id}",
                )
            return health

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"获取节点健康状态失败: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"获取节点健康状态失败: {str(e)}",
            )

    @app.get(
        "/api/v1/cluster/health",
        response_model=ClusterHealthResponse,
        tags=["监控"],
        summary="获取集群健康状态",
        description="获取整个集群的健康状态摘要",
    )
    async def get_cluster_health():
        """获取集群健康状态"""
        try:
            health = await heartbeat_monitor.get_cluster_health_summary()
            return health

        except Exception as e:
            logger.error(f"获取集群健康状态失败: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"获取集群健康状态失败: {str(e)}",
            )

    @app.post(
        "/api/v1/cluster/check-heartbeat",
        tags=["监控"],
        summary="执行心跳检查",
        description="手动执行一次心跳检查，返回超时节点列表",
    )
    async def check_heartbeat():
        """执行心跳检查"""
        try:
            result = await heartbeat_monitor.check_heartbeat()
            return result

        except Exception as e:
            logger.error(f"心跳检查失败: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"心跳检查失败: {str(e)}",
            )

    return app


def _node_to_response(node: NodeInfo) -> dict:
    """将NodeInfo对象转换为响应字典"""
    return {
        "node_id": node.node_id,
        "hostname": node.hostname,
        "platform": node.platform,
        "arch": node.arch,
        "status": node.status.value,
        "available_skills": node.available_skills,
        "max_concurrent_tasks": node.max_concurrent_tasks,
        "running_tasks": node.running_tasks,
        "ip_address": node.ip_address,
        "tailscale_ip": node.tailscale_ip,
        "port": node.port,
        "cpu_usage": node.cpu_usage,
        "memory_usage": node.memory_usage,
        "disk_usage": node.disk_usage,
        "total_tasks_processed": node.total_tasks_processed,
        "successful_tasks": node.successful_tasks,
        "failed_tasks": node.failed_tasks,
        "average_execution_time": node.average_execution_time,
        "registered_at": node.registered_at.isoformat() if node.registered_at else None,
        "last_heartbeat": node.last_heartbeat.isoformat() if node.last_heartbeat else None,
        "tags": node.tags,
    }


# ========== API 服务器 ==========


class APIServer:
    """API服务器"""

    def __init__(
        self,
        node_service: NodeRegistrationService,
        heartbeat_monitor: HeartbeatMonitor,
        config: Config,
    ):
        """
        初始化API服务器

        Args:
            node_service: 节点注册服务
            heartbeat_monitor: 心跳监控服务
            config: 配置对象
        """
        self.node_service = node_service
        self.heartbeat_monitor = heartbeat_monitor
        self.config = config
        self.app = create_api_app(node_service, heartbeat_monitor)
        self.server: Optional[Server] = None

    async def start(self):
        """启动API服务器"""
        host = self.config.coordinator.host
        port = self.config.coordinator.port

        logger.info(f"启动API服务器: http://{host}:{port}")

        config = UvicornConfig(
            app=self.app,
            host=host,
            port=port,
            log_config=None,  # 使用我们自己的日志配置
        )

        self.server = Server(config)
        await self.server.serve()

    async def stop(self):
        """停止API服务器"""
        if self.server:
            logger.info("停止API服务器")
            self.server.should_exit = True
