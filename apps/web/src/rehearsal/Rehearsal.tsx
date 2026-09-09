import { useWorkflow, type WorkflowStep, sessionStep } from './useWorkflow'
import { RehearsalHeader } from './RehearsalHeader'
import { RehearsalStepper } from './RehearsalStepper'
import { SceneSetupStep } from './SceneSetupStep'
import { SoundIssuesStep } from './SoundIssuesStep'
import { ReviewChangeStep } from './ReviewChangeStep'
import { CompareTakesStep } from './CompareTakesStep'
import { CheckReportStep } from './CheckReportStep'
import { useRehearsalAudio } from './useRehearsalAudio'
import './rehearsal.css'


export function Rehearsal({ report = false }: { report?: boolean }) {
  const workflow = useWorkflow({ report })
  const audio = useRehearsalAudio(workflow.session, workflow.step)

  const currentMaxStep: WorkflowStep = report
    ? 'report'
    : workflow.session
    ? sessionStep(workflow.session)
    : 'scene'

  const handleSelectTab = (tab: 'check' | 'report') => {
    if (tab === 'report') {
      workflow.setStep('report')
    } else {
      if (workflow.step === 'report') {
        const target = workflow.session?.state === 'NO_RISK'
          ? 'scene'
          : workflow.session?.comparison
          ? 'compare'
          : workflow.session?.baseline
          ? 'sound'
          : 'scene'
        workflow.setStep(target)
      }
    }
  }

  // Synchronize preset changes if session exists
  const handlePresetChange = (newPreset: string) => {
    workflow.setPreset(newPreset)
  }

  return (
    <div className={`sl-workspace rehearsal-app-root step-theme-${workflow.step}`}>
      {/* Header Navigation */}
      <RehearsalHeader
        step={workflow.step}
        onSelectTab={handleSelectTab}
        sceneName="Alleyway dialogue"
      />

      {/* Stepper Navigation */}
      <RehearsalStepper
        currentStep={workflow.step}
        session={workflow.session}
        maxAllowedStep={currentMaxStep}
        onStepClick={workflow.setStep}
      />

      {/* Notification Banners */}
      {workflow.busy && (
        <div role="status" className="rehearsal-banner banner-busy">
          <span>{workflow.busy}… Live cloud steps may take up to three minutes. Keep this page open.</span>
        </div>
      )}

      {/* Active Server Operation banner before resumable */}
      {workflow.session?.operation && !workflow.session.operation.resumable && (
        <div role="status" className="rehearsal-banner banner-busy">
          <span>Server operation in progress ({workflow.session.operation.kind || 'running'}). Refresh status to check completion.</span>
          <button
            type="button"
            className="banner-refresh-btn"
            disabled={!!workflow.busy}
            onClick={() => void workflow.refresh()}
          >
            Refresh status
          </button>
        </div>
      )}

      {workflow.error && (
        <div role="alert" className="rehearsal-banner banner-error">
          <div className="banner-error-content">
            <strong>We could not complete that step.</strong>
            <p>{workflow.error}</p>
          </div>
          <div className="flex items-center gap-2">
            {workflow.session?.comparison && (
              <button
                type="button"
                className="banner-resume-btn"
                disabled={!!workflow.busy}
                onClick={() => void workflow.retry()}
              >
                Retry fix
              </button>
            )}
            {workflow.session && (
              <button
                type="button"
                className="banner-refresh-btn"
                disabled={!!workflow.busy}
                onClick={() => void workflow.refresh()}
              >
                Refresh session
              </button>
            )}
          </div>
        </div>
      )}

      {workflow.session?.operation?.resumable && (
        <div className="rehearsal-banner banner-notice">
          <span>A saved operation can resume. Completed work will be reused.</span>
          <button
            type="button"
            className="banner-resume-btn"
            disabled={!!workflow.busy}
            onClick={() => void workflow.resume()}
          >
            Resume saved operation
          </button>
        </div>
      )}

      {/* Main Step Content View */}
      <main id="main-content" className="rehearsal-main-stage">
        {workflow.step === 'scene' && (
          <SceneSetupStep
            preset={workflow.preset}
            onPresetChange={handlePresetChange}
            mode={workflow.mode}
            onModeChange={workflow.setMode}
            readiness={workflow.readiness}
            busy={workflow.busy}
            hasSession={Boolean(workflow.session)}
            onStartAnotherCheck={() => {
              workflow.reset()
            }}
            onCheckSound={() => void workflow.checkSound()}
            onPlaySample={audio.playRawSample}
            onPauseSample={audio.pause}
            isPlaying={audio.isPlaying}
            currentTime={audio.currentTime}
            onSeek={audio.seek}
            audioError={audio.error}
          />
        )}

        {workflow.step === 'sound' && (
          <SoundIssuesStep
            session={workflow.session}
            busy={workflow.busy}
            onFindFix={() => void workflow.findFix()}
            onBackToScene={() => workflow.setStep('scene')}
            onPlaySection={audio.playSection}
            onPauseSection={audio.pause}
            isPlaying={audio.isPlaying}
            currentTime={audio.currentTime}
            isMuted={audio.isMuted}
            onToggleMute={audio.toggleMute}
            onSeek={audio.seek}
            currentPhrase={audio.currentPhrase}
            condition={audio.condition}
            audioError={audio.error}
          />
        )}

        {workflow.step === 'change' && (
          <ReviewChangeStep
            session={workflow.session}
            busy={workflow.busy}
            onInterpret={workflow.interpret}
            onConfirm={workflow.confirm}
            onTestChange={workflow.testChange}
            onBackToSound={() => workflow.setStep('sound')}
          />
        )}

        {workflow.step === 'compare' && (
          <CompareTakesStep
            session={workflow.session}
            busy={workflow.busy}
            onViewReport={() => workflow.setStep('report')}
            onBackToChange={() => workflow.setStep('change')}
            onPlayTrack={audio.playTrack}
            onSeekTrack={audio.seekTrack}
            onPauseTrack={audio.pause}
            activeTrack={audio.activeTrack}
            isPlaying={audio.isPlaying}
            currentTime={audio.currentTime}
            isMuted={audio.isMuted}
            onToggleMute={audio.toggleMute}
            onSeek={audio.seek}
            onRetry={() => void workflow.retry()}
            selectedMicId={audio.selectedMicId}
            onSelectMic={audio.selectMic}
            currentPhrase={audio.currentPhrase}
            condition={audio.condition}
            audioError={audio.error}
          />
        )}


        {workflow.step === 'report' && (
          <CheckReportStep
            session={workflow.session}
            busy={workflow.busy}
            onStartAnotherCheck={() => {
              workflow.reset()
              workflow.setStep('scene')
            }}
          />
        )}
      </main>
    </div>
  )
}

export default Rehearsal
