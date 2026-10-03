/**
 * Providers wrap the router, not the other way round.
 *
 * The chat stream in particular has to outlive a route change: a question typed
 * on the upload screen is sent there and answered on the workspace, and a
 * provider mounted per-route would drop the stream mid-turn.
 */

import { RouterProvider, useRouter } from '@/app/router'
import WakeNotice from '@/components/WakeNotice'
import Home from '@/routes/Home'
import Report from '@/routes/Report'
import Upload from '@/routes/Upload'
import Workspace from '@/routes/Workspace'
import { BackendProvider } from '@/state/BackendContext'
import { ChatProvider } from '@/state/ChatContext'
import { DatasetsProvider } from '@/state/DatasetsContext'
import { ProposalsProvider } from '@/state/ProposalsContext'

function Screen() {
  const { route } = useRouter()
  if (route === '/upload') return <Upload />
  if (route === '/workspace') return <Workspace />
  if (route === '/report') return <Report />
  return <Home />
}

export default function App() {
  return (
    <BackendProvider>
      <DatasetsProvider>
        <ChatProvider>
          <ProposalsProvider>
            <RouterProvider>
              <Screen />
              <WakeNotice />
            </RouterProvider>
          </ProposalsProvider>
        </ChatProvider>
      </DatasetsProvider>
    </BackendProvider>
  )
}
