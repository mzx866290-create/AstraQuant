"""
统一异常定义
"""
from fastapi import HTTPException, status


class StockPlatformException(Exception):
    """基础异常类"""

    def __init__(self, message: str, code: str = "UNKNOWN_ERROR"):
        self.message = message
        self.code = code
        super().__init__(message)


class AuthenticationException(StockPlatformException):
    """认证异常"""

    def __init__(self, message: str = "认证失败"):
        super().__init__(message, "AUTH_ERROR")


class AuthorizationException(StockPlatformException):
    """授权异常"""

    def __init__(self, message: str = "无权限访问"):
        super().__init__(message, "AUTHORIZATION_ERROR")


class ResourceNotFoundException(StockPlatformException):
    """资源未找到异常"""

    def __init__(self, resource: str = "资源"):
        super().__init__(f"{resource}不存在", "RESOURCE_NOT_FOUND")


class ValidationException(StockPlatformException):
    """数据验证异常"""

    def __init__(self, message: str = "数据验证失败"):
        super().__init__(message, "VALIDATION_ERROR")


class DataSourceException(StockPlatformException):
    """数据源异常"""

    def __init__(self, message: str = "数据源错误"):
        super().__init__(message, "DATA_SOURCE_ERROR")


class DatabaseException(StockPlatformException):
    """数据库异常"""

    def __init__(self, message: str = "数据库错误"):
        super().__init__(message, "DATABASE_ERROR")


class CacheException(StockPlatformException):
    """缓存异常"""

    def __init__(self, message: str = "缓存错误"):
        super().__init__(message, "CACHE_ERROR")


# FastAPI HTTPException 便捷函数
def raise_unauthorized():
    """未授权"""
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="未授权",
        headers={"WWW-Authenticate": "Bearer"},
    )


def raise_forbidden():
    """禁止访问"""
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="禁止访问",
    )


def raise_not_found(resource: str = "资源"):
    """资源不存在"""
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"{resource}不存在",
    )


def raise_bad_request(detail: str = "请求参数错误"):
    """请求参数错误"""
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=detail,
    )


def raise_internal_error(detail: str = "服务器内部错误"):
    """服务器内部错误"""
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=detail,
    )
