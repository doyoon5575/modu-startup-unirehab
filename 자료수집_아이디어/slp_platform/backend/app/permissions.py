"""
사용자별 권한(기획서 3장, UI 명세 '상태와 예외 처리').
'치료사가 확인한다'는 문구가 아니라, 확인하지 않으면 확정되지 않는 권한 구조로 구현한다.
"""
from .enums import Role


class PermissionError_(Exception):
    pass


ACTIONS = {
    "patient.view_clinical":   {Role.THERAPIST, Role.TRAINEE, Role.SUPERVISOR},
    "patient.edit":            {Role.THERAPIST, Role.SUPERVISOR},
    "goal.confirm":            {Role.THERAPIST, Role.SUPERVISOR},
    "session.plan":            {Role.THERAPIST, Role.SUPERVISOR, Role.TRAINEE},   # 실습생은 초안만
    "trial.review":            {Role.THERAPIST, Role.SUPERVISOR, Role.TRAINEE},   # 실습생은 검토 초안만
    "session.finalize_result": {Role.THERAPIST, Role.SUPERVISOR},
    "plan.approve":            {Role.THERAPIST, Role.SUPERVISOR},
    "plan.request_approval":   {Role.TRAINEE},
    "home.assign":             {Role.THERAPIST, Role.SUPERVISOR},
    "home.perform":            {Role.PATIENT, Role.CAREGIVER},
    "org.manage":              {Role.ORG_ADMIN},
    "trainee.feedback":        {Role.SUPERVISOR},
}


def can(user, action: str) -> bool:
    roles = ACTIONS.get(action, set())
    if user.role not in roles:
        return False
    if action == "patient.view_clinical" and not user.clinical_access:
        return False
    return True


def require(user, action: str):
    if not can(user, action):
        # 승인 권한 없는 계정: 승인 버튼 대신 권한 안내
        raise PermissionError_(f"[{user.role.value}] 계정은 '{action}' 권한이 없습니다. 승인 권한이 있는 언어재활사·지도자에게 요청하세요.")
