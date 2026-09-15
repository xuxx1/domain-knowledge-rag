"""RAG 评测路由：测试问题集管理 + 运行评测 + 查看评测历史

接口：
- GET  /api/eval/questions                    列出全部评测问题（可按 kb_id 过滤）
- POST /api/eval/questions                    新增评测问题
- PUT  /api/eval/questions/{id}               更新评测问题（含 ground truth）
- DELETE /api/eval/questions/{id}             删除评测问题
- POST /api/eval/runs                         运行一轮评测（跑一批问题）
- GET  /api/eval/runs                         查看评测历史
- GET  /api/eval/runs/{id}                    查看单次评测详情（含每问 Top-K 与命中）
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import (
    EvalQuestion,
    EvalRun,
    KnowledgeBase,
    get_db,
)
from ..schemas import (
    EvalQuestionCreate,
    EvalQuestionOut,
    EvalQuestionUpdate,
    EvalRunOut,
    EvalRunRequest,
)
from ..services.evaluator import run_eval, save_run

router = APIRouter(prefix="/eval", tags=["RAG评测"])


# ---------- 测试问题集 ----------
@router.get("/questions", response_model=list[EvalQuestionOut])
def list_questions(
    kb_id: int | None = Query(None, description="按知识库过滤"),
    db: Session = Depends(get_db),
):
    stmt = select(EvalQuestion).order_by(EvalQuestion.kb_id, EvalQuestion.id)
    if kb_id is not None:
        stmt = stmt.where(EvalQuestion.kb_id == kb_id)
    return db.execute(stmt).scalars().all()


@router.post("/questions", response_model=EvalQuestionOut)
def create_question(body: EvalQuestionCreate, db: Session = Depends(get_db)):
    if not db.get(KnowledgeBase, body.kb_id):
        raise HTTPException(404, "知识库不存在")
    q = EvalQuestion(
        kb_id=body.kb_id,
        question=body.question,
        ground_truth_doc_ids=body.ground_truth_doc_ids,
        ground_truth_chunk_ids=body.ground_truth_chunk_ids,
        note=body.note,
    )
    db.add(q)
    db.commit()
    db.refresh(q)
    return q


@router.put("/questions/{qid}", response_model=EvalQuestionOut)
def update_question(qid: int, body: EvalQuestionUpdate, db: Session = Depends(get_db)):
    q = db.get(EvalQuestion, qid)
    if not q:
        raise HTTPException(404, "评测问题不存在")
    if body.question is not None:
        q.question = body.question
    if body.ground_truth_doc_ids is not None:
        q.ground_truth_doc_ids = body.ground_truth_doc_ids
    if body.ground_truth_chunk_ids is not None:
        q.ground_truth_chunk_ids = body.ground_truth_chunk_ids
    if body.note is not None:
        q.note = body.note
    db.commit()
    db.refresh(q)
    return q


@router.delete("/questions/{qid}")
def delete_question(qid: int, db: Session = Depends(get_db)):
    q = db.get(EvalQuestion, qid)
    if not q:
        raise HTTPException(404, "评测问题不存在")
    db.delete(q)
    db.commit()
    return {"ok": True}


# ---------- 运行评测 ----------
@router.post("/runs", response_model=EvalRunOut)
def create_run(body: EvalRunRequest, db: Session = Depends(get_db)):
    if not db.get(KnowledgeBase, body.kb_id):
        raise HTTPException(404, "知识库不存在")
    # 校验问题属于该知识库（若指定了 question_ids）
    if body.question_ids:
        for qid in body.question_ids:
            q = db.get(EvalQuestion, qid)
            if not q:
                raise HTTPException(404, f"评测问题 {qid} 不存在")
            if q.kb_id != body.kb_id:
                raise HTTPException(400, f"评测问题 {qid} 不属于知识库 {body.kb_id}")
    result = run_eval(body.kb_id, body.question_ids)
    run = save_run(body.kb_id, body.question_ids, result)
    return run


@router.get("/runs")
def list_runs(
    kb_id: int | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    stmt = select(EvalRun).order_by(EvalRun.id.desc()).limit(limit)
    if kb_id is not None:
        stmt = stmt.where(EvalRun.kb_id == kb_id)
    runs = db.execute(stmt).scalars().all()
    return [
        {
            "id": r.id,
            "kb_id": r.kb_id,
            "status": r.status,
            "elapsed_s": r.elapsed_s,
            "summary": r.summary,
            "created_at": r.created_at,
        }
        for r in runs
    ]


@router.get("/runs/{rid}")
def get_run(rid: int, db: Session = Depends(get_db)):
    run = db.get(EvalRun, rid)
    if not run:
        raise HTTPException(404, "评测记录不存在")
    return {
        "id": run.id,
        "kb_id": run.kb_id,
        "question_ids": run.question_ids,
        "items": run.items,
        "summary": run.summary,
        "status": run.status,
        "elapsed_s": run.elapsed_s,
        "created_at": run.created_at,
    }