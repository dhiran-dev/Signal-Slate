import {render,screen,cleanup} from '@testing-library/react'
import {afterEach,expect,it} from 'vitest'
import {Citations} from './Citations'
import type {Session} from './types'
afterEach(cleanup)
it('replays original bound evidence after a later comparison without substituting runs',()=>{render(<Citations session={{finding:{evidence_ids:['ev-1']},comparison:{run_id:'later-comparison'},finding_evidence:[{evidence_id:'ev-1',run_id:'original-baseline',mic_id:'mic_1',offset_ms:4900,source_tool:'query_loki_logs',query_hash:'q',observation_type:'dropout',value:true,unit:'boolean',retrieval_time:'2026-09-09T00:00:00Z',config_hash:'original-config'}]} as Session}/>);expect(screen.getByText('original-baseline')).toBeInTheDocument();expect(screen.getByText('dropout: true boolean')).toBeInTheDocument();expect(screen.queryByText('later-comparison')).not.toBeInTheDocument()})
it('makes missing original citation explicit',()=>{render(<Citations session={{finding:{evidence_ids:['missing']},finding_evidence:[]} as unknown as Session}/>);expect(screen.getByText(/original envelope is unavailable/)).toBeInTheDocument()})
