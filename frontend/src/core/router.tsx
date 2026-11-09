/**
 * 화면 경로(라우팅) 정의.
 *
 * 새 화면을 만들면 여기에 경로를 추가한다.
 * 로그인이 필요한 화면은 `RequireAuth` 아래에 두고, 사이드바가 있는 화면은 `AppShell` 안에 둔다.
 */
import { Navigate, Outlet, Route, Routes } from 'react-router-dom'
import { AppShell } from '../ui/AppShell'
import { LoadingScreen } from '../ui/LoadingScreen'
import { AccountsView } from '../views/admin/AccountsView'
import { AllTicketsView } from '../views/admin/AllTicketsView'
import { AiOpsView } from '../views/admin/AiOpsView'
import { AdminStatsView } from '../views/admin/AdminStatsView'
import { DashView } from '../views/admin/DashView'
import { GuidesView } from '../views/admin/GuidesView'
import { OpsView } from '../views/admin/OpsView'
import { AuditLogView } from '../views/admin/AuditLogView'
import { SecurityView } from '../views/admin/SecurityView'
import { FaqView } from '../views/faq/FaqView'
import { GuideLibraryView } from '../views/docs/GuideLibraryView'
import { ChatView } from '../views/inquiry/ChatView'
import { InquiryListView } from '../views/inquiry/InquiryListView'
import { NewInquiryView } from '../views/inquiry/NewInquiryView'
import { PendingChatView } from '../views/inquiry/PendingChatView'
import { LoginView } from '../views/login/LoginView'
import { StatsView } from '../views/staff/StatsView'
import { MyDashView } from '../views/staff/MyDashView'
import { CalendarView } from '../views/staff/CalendarView'
import { QueueView } from '../views/staff/QueueView'
import { HOME_BY_ROLE } from './roles'
import { useAuth } from './session'

/**
 * 로그인한 사용자만 들어갈 수 있는 영역.
 * 화면 이동을 막는 편의 기능일 뿐이며, 실제 권한 검사는 백엔드가 한다. (SRS NFR-SEC-02)
 */
function RequireAuth() {
  const { user, loading } = useAuth()
  if (loading) return <LoadingScreen /> // 저장된 토큰을 확인하는 동안 (0.3초 넘게 걸릴 때만) 확인 중이라고 알린다
  if (!user) return <Navigate to="/login" replace />
  return <Outlet />
}

/** 알 수 없는 주소로 오면 로그인 상태에 맞는 첫 화면으로 보낸다. */
/** 통계: 관리자는 티켓·AI 상담 전체, 담당자는 내 통계·팀 통계 */
function StatsEntry() {
  const { user } = useAuth()
  return user?.serviceRole === 'ADMIN' ? <AdminStatsView /> : <StatsView />
}

function Landing() {
  const { user, loading } = useAuth()
  if (loading) return <LoadingScreen />
  return <Navigate to={user ? HOME_BY_ROLE[user.serviceRole] : '/login'} replace />
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginView />} />

      {/* 로그인 필요 영역 */}
      <Route element={<RequireAuth />}>
        {/* 사이드바가 있는 화면들 */}
        <Route element={<AppShell />}>
          {/* 문의 (모든 역할 공통) */}
          <Route path="/new" element={<NewInquiryView />} />
          <Route path="/list" element={<InquiryListView />} />
          <Route path="/chat/new" element={<PendingChatView />} />
          <Route path="/chat/:id" element={<ChatView />} />
          <Route path="/faq" element={<FaqView />} />
          <Route path="/docs" element={<GuideLibraryView />} />
          {/* 담당자·관리자 */}
          <Route path="/my" element={<MyDashView />} />
          <Route path="/stats" element={<StatsEntry />} />
          <Route path="/queue" element={<QueueView />} />
          <Route path="/queue/:ticketId" element={<QueueView />} />
          <Route path="/calendar" element={<CalendarView />} />
          <Route path="/dash" element={<DashView />} />
          <Route path="/accounts" element={<AccountsView />} />
          <Route path="/ops" element={<OpsView />} />
          <Route path="/security" element={<SecurityView />} />
          <Route path="/audit" element={<AuditLogView />} />
          <Route path="/guides" element={<GuidesView />} />
          <Route path="/ai" element={<AiOpsView />} />
          <Route path="/tickets" element={<AllTicketsView />} />
          <Route path="/tickets/:ticketId" element={<AllTicketsView />} />
        </Route>
      </Route>

      <Route path="*" element={<Landing />} />
    </Routes>
  )
}
