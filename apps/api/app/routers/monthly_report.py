from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.farm_clock import farm_today
from app.core.security import require_minimum_role
from app.db.models import AuditEvent, Farm, User
from app.db.session import get_db_session
from app.routers.registry import resolve_current_farm
from app.schemas.monthly_report import MonthlyReport
from app.services.monthly_report import build_monthly_report
from app.services.monthly_export import build_monthly_workbook
from app.services.production_export import MEDIA_TYPE

router = APIRouter(prefix='/api/reports', tags=['reports'])
DB = Annotated[AsyncSession, Depends(get_db_session)]
CurrentFarm = Annotated[Farm, Depends(resolve_current_farm)]


@router.get('/monthly', response_model=MonthlyReport)
async def read_monthly(
    session: DB, farm: CurrentFarm,
    _: Annotated[User, Depends(require_minimum_role('operator'))],
    inicio: str = Query(pattern=r'^\d{4}-(0[1-9]|1[0-2])$'),
    fim: str = Query(pattern=r'^\d{4}-(0[1-9]|1[0-2])$'),
    simulate_current: bool = Query(False, alias='simular_atuais'),
) -> MonthlyReport:
    try:
        return await build_monthly_report(session, farm, inicio, fim, farm_today(), simulate_current)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@router.get('/monthly/export')
async def export_monthly(
    session: DB, farm: CurrentFarm,
    user: Annotated[User, Depends(require_minimum_role('reviewer'))],
    report: Annotated[MonthlyReport, Depends(read_monthly)],
):
    content = build_monthly_workbook(report)
    session.add(AuditEvent(farm_id=farm.id, actor=user.email, action='monthly_report_exported',
        entity_type='farm', entity_id=farm.id,
        new_value={'inicio': report.start_month, 'fim': report.end_month, 'simular_atuais': report.current_values_simulation}))
    await session.commit()
    return Response(content, media_type=MEDIA_TYPE, headers={
        'Content-Disposition': f'attachment; filename="relatorio-mensal-{report.start_month}-a-{report.end_month}.xlsx"',
        'Cache-Control': 'no-store',
    })
