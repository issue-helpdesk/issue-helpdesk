/**
 * 팀별 개인 현황 (관리자, 캘린더 화면 맨 아래). 담당 그룹마다 구성원의 근무·부재, 처리 대기·처리 중 건수, 긴급도 분포를 보여 준다.
 * 구성원·부재·업무량은 RF-04·TO-01·TK-05 로 읽는다 (api/reference.ts). 운영 현황에서 옮겨 왔다.
 */
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { URGENCY_LABEL } from '../../api/catalog'
import { listBoard, listSupportGroups, type Candidate, type SupportGroupRef } from '../../api/reference'
import { watchTickets } from '../../api/tickets'
import { useAuth } from '../../core/session'
import { Icon } from '../../ui/Icon'
import { URGS } from '../staff/StatsView'

export function TeamBoard() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [groups, setGroups] = useState<SupportGroupRef[]>([])
  const [people, setPeople] = useState<Record<string, Candidate[]>>({})
  const [peopleErr, setPeopleErr] = useState('')
  const [chip, setChip] = useState('')
  const [tick, setTick] = useState(0)
  useEffect(() => watchTickets(() => setTick((n) => n + 1)), [])
  useEffect(() => {
    listSupportGroups().then((r) => r.ok && setGroups(r.data))
  }, [])
  useEffect(() => {
    if (!user || !groups.length) return
    let alive = true
    listBoard(user).then((r) => {
      if (!alive) return
      if (!r.ok) {
        setPeopleErr(r.error.message)
        setPeople({})
        return
      }
      setPeopleErr('')
      setPeople(r.data)
    })
    return () => {
      alive = false
    }
  }, [user, groups, tick])

  const grp = chip || groups[0]?.name || ''
  const members = people[grp] ?? []

  return (
    <section className="panel" aria-label="팀별 개인 현황">
      <div className="sech">
        <div>
          <h3 className="sht">팀별 개인 현황</h3>
          <p className="shs">
            팀별로 근무 여부와 진행 중 티켓의 긴급도를 확인해요. 이름을 누르면 그 담당자의 처리 대기·처리 중 티켓을 볼 수 있어요. 칩 숫자는 근무/전체 인원이에요.
          </p>
        </div>
      </div>
      {peopleErr ? (
        <div className="alert info" role="status">
          <Icon name="alert" />
          <div>{peopleErr}</div>
        </div>
      ) : (
        <>
          <div className="ocurh">
            <div className="subc" role="group" aria-label="담당 그룹">
              {groups.map((g) => {
                const list = people[g.name] ?? []
                return (
                  <button key={g.id} type="button" className={`chip${g.name === grp ? ' on' : ''}`} aria-pressed={g.name === grp} onClick={() => setChip(g.name)}>
                    {g.name} <em>{`${list.filter((c) => c.avail).length}/${list.length}`}</em>
                  </button>
                )
              })}
            </div>
          </div>
          <div className="tw" id="ocur-b">
            <table className="tbl ptbl">
              <colgroup>
                <col style={{ width: '14%' }} />
                <col style={{ width: '13%' }} />
                <col style={{ width: '11%' }} />
                <col style={{ width: '11%' }} />
                <col style={{ width: '22%' }} />
                <col style={{ width: '12%' }} />
                <col style={{ width: '17%' }} />
              </colgroup>
              <thead>
                <tr>
                  <th>이름</th>
                  <th>오늘 상태</th>
                  <th className="c">처리 대기</th>
                  <th className="c">처리 중</th>
                  <th>
                    긴급도 <span className="small muted">(처리 대기 + 처리 중)</span>
                  </th>
                  <th>ITSM 계정</th>
                  <th>비고</th>
                </tr>
              </thead>
              <tbody>
                {members.map((c) => {
                  const notes = [!c.avail && '부재 중 · 자동배정 제외', !c.jira && 'ITSM 배정 반영 불가'].filter(Boolean).join(' · ')
                  return (
                    <tr key={c.id}>
                      <td>
                        <button type="button" className="lk" title={`${c.name} 담당자의 처리 대기·처리 중 티켓 보기`} onClick={() => navigate(`/tickets?staff=${encodeURIComponent(c.name)}&st=open`)}>
                          {c.name}
                        </button>
                      </td>
                      <td>
                        <span className={`stt ${c.avail ? 'on' : 'off'}`}>
                          <i />
                          {c.avail ? '근무' : `부재 (${c.leave ?? '연차'})`}
                        </span>
                      </td>
                      <td className="c">{c.rdy}건</td>
                      <td className="c">{c.wip}건</td>
                      <td>
                        <span className="pcs">
                          {URGS.map((p) => (
                            <span key={p} className={`pcn ${c.pri[p] ? `pri-${p.toLowerCase()}` : 'z'}`} title={URGENCY_LABEL[p]}>
                              {URGENCY_LABEL[p]} <b>{c.pri[p]}</b>
                            </span>
                          ))}
                        </span>
                      </td>
                      <td>{c.jira ? '연결됨' : <span className="od">⚠ 미연결</span>}</td>
                      <td className="small muted">{notes || '-'}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  )
}
