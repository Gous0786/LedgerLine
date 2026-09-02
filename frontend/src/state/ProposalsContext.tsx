/**
 * Match proposals, shared between the activity stream (where they appear as
 * the agent produces them), the modal, and the reconciled tab.
 *
 * Refreshes when the agent goes idle, so cards land as soon as a run finishes
 * without polling while it works.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import {
  getCoverage,
  listProposals,
  listRules,
  proposalSummary,
  setProposalStatus,
  setProposalStatusBatch,
  trustRule,
  type BatchStatusResult,
  type Coverage,
  type Proposal,
  type ProposalStatus,
  type ProposalSummary,
  type RuleTrust,
} from '@/lib/api'
import { useChatState } from '@/state/ChatContext'

interface ProposalsContextValue {
  proposals: Proposal[]
  summary: ProposalSummary | null
  coverage: Coverage | null
  actMany: (ids: number[], status: ProposalStatus) => Promise<BatchStatusResult>
  rules: RuleTrust[]
  approveRule: (rule: string) => Promise<void>
  byId: (id: number) => Proposal | undefined
  pending: Proposal[]
  accepted: Proposal[]
  openId: number | null
  open: (id: number) => void
  close: () => void
  act: (id: number, status: ProposalStatus) => Promise<void>
  refresh: () => Promise<void>
  busy: boolean
}

const Ctx = createContext<ProposalsContextValue | null>(null)

export function ProposalsProvider({ children }: { children: React.ReactNode }) {
  const { busy: agentBusy } = useChatState()
  const [proposals, setProposals] = useState<Proposal[]>([])
  const [summary, setSummary] = useState<ProposalSummary | null>(null)
  const [rules, setRules] = useState<RuleTrust[]>([])
  const [coverage, setCoverage] = useState<Coverage | null>(null)
  const [openId, setOpenId] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)

  const refresh = useCallback(async () => {
    try {
      const [list, sum, rs, cov] = await Promise.all([
        listProposals(''),
        proposalSummary(),
        listRules(),
        getCoverage(),
      ])
      setProposals(list)
      setSummary(sum)
      setRules(rs)
      setCoverage(cov)
    } catch {
      /* backend may not be up yet */
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  // Pull once the agent stops working -- that is when new proposals exist.
  useEffect(() => {
    if (!agentBusy) void refresh()
  }, [agentBusy, refresh])

  const act = useCallback(
    async (id: number, status: ProposalStatus) => {
      setBusy(true)
      // optimistic: the row should move out of the queue immediately
      setProposals((all) => all.map((p) => (p.id === id ? { ...p, status } : p)))
      try {
        await setProposalStatus(id, status)
        await refresh()
      } catch {
        await refresh()
      } finally {
        setBusy(false)
      }
    },
    [refresh],
  )

  /** Accepting a chain is accepting its legs -- each still gated on its own,
   *  so a partial result is normal and the caller reports what was held back. */
  const actMany = useCallback(
    async (ids: number[], status: ProposalStatus): Promise<BatchStatusResult> => {
      setBusy(true)
      setProposals((all) =>
        all.map((p) => (ids.includes(p.id) ? { ...p, status } : p)),
      )
      try {
        return await setProposalStatusBatch(ids, status)
      } finally {
        await refresh()
        setBusy(false)
      }
    },
    [refresh],
  )

  const approveRule = useCallback(
    async (rule: string) => {
      setBusy(true)
      try {
        await trustRule(rule)
        await refresh()
      } finally {
        setBusy(false)
      }
    },
    [refresh],
  )

  const value = useMemo<ProposalsContextValue>(() => {
    const byId = (id: number) => proposals.find((p) => p.id === id)
    return {
      proposals,
      summary,
      coverage,
      rules,
      approveRule,
      actMany,
      byId,
      pending: proposals.filter((p) => p.status === 'pending' || p.status === 'review_later'),
      accepted: proposals.filter((p) => p.status === 'accepted'),
      openId,
      open: setOpenId,
      close: () => setOpenId(null),
      act,
      refresh,
      busy,
    }
  }, [proposals, summary, coverage, rules, approveRule, actMany, openId, act, refresh, busy])

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useProposals(): ProposalsContextValue {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useProposals must be used inside <ProposalsProvider>')
  return ctx
}
