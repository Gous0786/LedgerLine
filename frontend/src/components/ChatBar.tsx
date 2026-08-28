import { useRef, useState } from 'react'
import { useChatState } from '@/state/ChatContext'
import { useDatasets } from '@/state/DatasetsContext'
import { PendingBanner } from '@/components/ProposalCards'

export default function ChatBar() {
  const { send, stop, busy } = useChatState()
  const { upload, busy: uploading } = useDatasets()
  const [input, setInput] = useState('')
  const fileInput = useRef<HTMLInputElement>(null)
  const textarea = useRef<HTMLTextAreaElement>(null)

  function submit() {
    if (!input.trim() || busy) return
    send(input)
    setInput('')
    if (textarea.current) textarea.current.style.height = 'auto'
  }

  return (
    <div className="shrink-0 space-y-2 px-4 pb-4">
      <PendingBanner />
      <div className="glass focus-within:border-accent/50 rounded-xl px-3 py-2.5 transition-colors">
        <textarea
          ref={textarea}
          rows={1}
          value={input}
          placeholder="Ask anything…"
          onChange={(e) => {
            setInput(e.target.value)
            e.target.style.height = 'auto'
            e.target.style.height = `${Math.min(e.target.scrollHeight, 160)}px`
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              submit()
            }
          }}
          className="w-full resize-none bg-transparent text-[13px] text-ink placeholder:text-faint focus:outline-none"
        />

        <div className="mt-1.5 flex items-center gap-3">
          <input
            ref={fileInput}
            type="file"
            accept=".csv,text/csv"
            multiple
            className="hidden"
            onChange={(e) => {
              void upload(e.target.files ?? [])
              e.target.value = ''
            }}
          />
          <button
            onClick={() => fileInput.current?.click()}
            disabled={uploading}
            className="text-[12px] text-faint transition-colors hover:text-muted disabled:opacity-40"
          >
            + Upload file
          </button>

          <button
            onClick={busy ? stop : submit}
            disabled={!busy && !input.trim()}
            className={
              'ml-auto flex size-7 items-center justify-center rounded-lg text-[13px] transition-colors ' +
              (busy
                ? 'bg-bad/20 text-bad hover:bg-bad/30'
                : input.trim()
                  ? 'bg-accent text-white hover:brightness-110'
                  : 'bg-line text-faint')
            }
          >
            {busy ? '■' : '↑'}
          </button>
        </div>
      </div>

      <p className="mt-1.5 text-center text-[10px] text-faint">
        Figures come from tool results, not the model. Verify before acting.
      </p>
    </div>
  )
}
