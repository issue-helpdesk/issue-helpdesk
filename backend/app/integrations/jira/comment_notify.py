"""Jira 댓글이 달렸을 때 누구에게 알림을 보낼지 정한다.

네트워크와 DB를 쓰지 않는다. 입력은 이미 알고 있는 값(댓글 작성자 accountId, 티켓의 문의자·담당자 사번)이고,
출력은 알림 받을 사번과 그렇게 정한 이유다. 알림을 저장하고 화면·Slack으로 보내는 일은 백엔드 몫이다.

    event = parse_jira_webhook(payload, delivery_id=...)
    if event.is_comment_created:
        comment = jira.get_comment(event.issue_key, event.comment.comment_id)   # 본문·작성자는 Jira에서 다시 읽는다
        route = route_comment(comment["author_account_id"],
                              requester_no=ticket.requester_no, assignee_no=ticket.assignee_no,
                              ignore_account_ids={bot_account_id})            # bot_account_id: JiraClient.check_auth()["account_id"]
        for emp_no in route.recipient_nos:
            ...  # 이 사번의 계정에 알림 저장 (route.reason 은 로그용)

문의자와 담당자는 Jira의 reporter·assignee 가 아니라 ITssue DB의 티켓에 저장된 사번을 쓴다.
(보고자는 API 토큰 계정이고, 이관한 티켓은 Jira 담당자가 비어 있을 수 있다.)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Collection, Mapping

from .accounts import employee_no_for


@dataclass(frozen=True)
class CommentRoute:
    recipient_nos: tuple[str, ...]  # 알림 받을 사번. 비어 있으면 알림을 보내지 않는다
    reason: str                     # 로그용. 아래 값 중 하나

    # to_assignee        문의자가 달았다 → 담당자에게
    # to_requester       담당자가 달았다 → 문의자에게
    # to_both            문의자도 담당자도 아닌 사람(팀장·관리자 등)이 달았다 → 둘 모두에게
    # ignored_author     작성자 정보가 없거나 ignore_account_ids(ITssue 봇 계정)에 있다
    # unknown_author     연결표에 없는 Jira 계정이다
    # self_comment       문의자와 담당자가 같은 사람이다
    # no_counterpart     받을 상대(담당자 미배정 등)가 없다


def route_comment(
    author_account_id: str | None,
    *,
    requester_no: str | None,
    assignee_no: str | None,
    accounts: Mapping[str, str] | None = None,
    ignore_account_ids: Collection[str] = (),
) -> CommentRoute:
    """댓글 작성자 기준으로 알림 받을 사번을 정한다. 작성자 본인에게는 보내지 않는다."""
    author = str(author_account_id or "").strip()
    ignored = {str(a).strip() for a in ignore_account_ids if a}
    if not author or author in ignored:
        return CommentRoute((), "ignored_author")

    author_no = employee_no_for(author, accounts)
    if author_no is None:
        return CommentRoute((), "unknown_author")

    requester = (requester_no or "").strip() or None
    assignee = (assignee_no or "").strip() or None
    if requester and requester == assignee == author_no:
        return CommentRoute((), "self_comment")

    if author_no == requester:
        return CommentRoute((assignee,), "to_assignee") if assignee else CommentRoute((), "no_counterpart")
    if author_no == assignee:
        return CommentRoute((requester,), "to_requester") if requester else CommentRoute((), "no_counterpart")

    both = tuple(dict.fromkeys(n for n in (requester, assignee) if n))
    return CommentRoute(both, "to_both") if both else CommentRoute((), "no_counterpart")
