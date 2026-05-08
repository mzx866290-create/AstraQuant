"""
AI 模型管理 API - 管理员专用
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from typing import Optional, List

from backend.shared.audit import audit_log
from backend.shared.database import get_db
from backend.shared.models import AIModel, User
from backend.shared.auth import require_admin
from backend.shared.schemas import AIModelCreate, AIModelUpdate, AIModelResponse

router = APIRouter(prefix="/models", tags=["管理员-模型管理"])


@router.get("", response_model=List[AIModelResponse])
async def list_models(
    skip: int = 0,
    limit: int = 100,
    is_active: Optional[bool] = None,
    current_user: User = Depends(require_admin()),
    db: Session = Depends(get_db),
):
    """获取所有AI模型列表"""
    query = db.query(AIModel)
    if is_active is not None:
        query = query.filter(AIModel.is_active == is_active)
    models = query.order_by(AIModel.sort_order, AIModel.id).offset(skip).limit(limit).all()
    return models


@router.post("", response_model=AIModelResponse)
async def create_model(
    data: AIModelCreate,
    request: Request,
    current_user: User = Depends(require_admin()),
    db: Session = Depends(get_db),
):
    """创建新AI模型"""
    from backend.shared.auth import encrypt_api_key

    model = AIModel(
        name=data.name,
        provider=data.provider,
        model_id=data.model_id,
        api_base_url=data.api_base_url,
        api_key_encrypted=encrypt_api_key(data.api_key),
        description=data.description,
        config=data.config,
        is_active=data.is_active,
        sort_order=data.sort_order,
        allowed_roles=data.allowed_roles,
        created_by=current_user.id,
    )
    db.add(model)
    audit_log(db, action="admin.model_create", actor=current_user, request=request, target=f"model:{data.name}")
    db.commit()
    db.refresh(model)
    return model


@router.put("/{model_id}", response_model=AIModelResponse)
async def update_model(
    model_id: int,
    data: AIModelUpdate,
    request: Request,
    current_user: User = Depends(require_admin()),
    db: Session = Depends(get_db),
):
    """更新AI模型"""
    model = db.query(AIModel).filter(AIModel.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="模型不存在")

    update_data = data.model_dump(exclude_unset=True)
    if "api_key" in update_data:
        from backend.shared.auth import encrypt_api_key
        update_data["api_key_encrypted"] = encrypt_api_key(update_data.pop("api_key"))

    for key, value in update_data.items():
        setattr(model, key, value)

    audit_log(db, action="admin.model_update", actor=current_user, request=request, target=f"model:{model_id}")
    db.commit()
    db.refresh(model)
    return model


@router.delete("/{model_id}")
async def delete_model(
    model_id: int,
    request: Request,
    current_user: User = Depends(require_admin()),
    db: Session = Depends(get_db),
):
    """删除AI模型"""
    model = db.query(AIModel).filter(AIModel.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="模型不存在")

    target = f"model:{model.id}:{model.name}"
    db.delete(model)
    audit_log(db, action="admin.model_delete", actor=current_user, request=request, target=target)
    db.commit()
    return {"message": "模型已删除"}


@router.post("/{model_id}/test")
async def test_model(
    model_id: int,
    request: Request,
    current_user: User = Depends(require_admin()),
    db: Session = Depends(get_db),
):
    """测试模型连通性"""
    model = db.query(AIModel).filter(AIModel.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="模型不存在")

    from backend.shared.auth import decrypt_api_key
    api_key = decrypt_api_key(model.api_key_encrypted)

    # 简单的连通性测试
    try:
        if model.provider == "openai":
            from openai import OpenAI
            client = OpenAI(api_key=api_key, base_url=model.api_base_url or None)
            response = client.chat.completions.create(
                model=model.model_id,
                messages=[{"role": "user", "content": "Hi"}],
                max_tokens=5,
            )
            audit_log(db, action="admin.model_test", actor=current_user, request=request, target=f"model:{model_id}:success")
            db.commit()
            return {"status": "success", "message": "连接成功", "response": "OK"}
        elif model.provider == "anthropic":
            from anthropic import Anthropic
            client = Anthropic(api_key=api_key)
            response = client.messages.create(
                model=model.model_id,
                max_tokens=5,
                messages=[{"role": "user", "content": "Hi"}],
            )
            audit_log(db, action="admin.model_test", actor=current_user, request=request, target=f"model:{model_id}:success")
            db.commit()
            return {"status": "success", "message": "连接成功", "response": "OK"}
        elif model.provider == "deepseek":
            from openai import OpenAI
            client = OpenAI(api_key=api_key, base_url=model.api_base_url or "https://api.deepseek.com")
            response = client.chat.completions.create(
                model=model.model_id,
                messages=[{"role": "user", "content": "Hi"}],
                max_tokens=5,
            )
            audit_log(db, action="admin.model_test", actor=current_user, request=request, target=f"model:{model_id}:success")
            db.commit()
            return {"status": "success", "message": "连接成功", "response": "OK"}
        else:
            audit_log(db, action="admin.model_test", actor=current_user, request=request, target=f"model:{model_id}:unsupported")
            db.commit()
            return {"status": "error", "message": f"不支持的 provider: {model.provider}"}
    except Exception as e:
        audit_log(db, action="admin.model_test", actor=current_user, request=request, target=f"model:{model_id}:error")
        db.commit()
        return {"status": "error", "message": f"连接失败: {str(e)}"}


@router.patch("/{model_id}/toggle")
async def toggle_model(
    model_id: int,
    request: Request,
    current_user: User = Depends(require_admin()),
    db: Session = Depends(get_db),
):
    """启用/禁用模型"""
    model = db.query(AIModel).filter(AIModel.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="模型不存在")

    model.is_active = not model.is_active
    audit_log(
        db,
        action="admin.model_toggle",
        actor=current_user,
        request=request,
        target=f"model:{model_id}:{'enabled' if model.is_active else 'disabled'}",
    )
    db.commit()
    return {"message": f"模型已{'启用' if model.is_active else '禁用'}", "is_active": model.is_active}
