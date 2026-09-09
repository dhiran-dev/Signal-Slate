import {test, expect, type Page} from '@playwright/test'

async function sample(page:Page, preset='a', completed=false) {
  const created=await page.request.post('/api/sessions',{data:{mode:'preview',preset}})
  expect(created.ok()).toBe(true)
  let session=await created.json()
  async function command(action:string,extra:Record<string,unknown>={}){
    const response=await page.request.post(`/api/sessions/${session.id}/${action}`,{headers:{'X-CSRF-Token':session.csrf_token},data:{revision:session.revision,...extra}})
    expect(response.ok()).toBe(true)
    session=await response.json()
    expect(session.error).toBeNull()
  }
  await command('baseline')
  if(completed){
    await command('investigate')
    await command('constraints',{text:'Exclude channel 11'})
    await command('confirm',{constraints:session.interpretation.constraints.map((c:Record<string,unknown>)=>({...c,confirmed:true}))})
    const p=session.candidate_plans[0]
    await command('approve',{approval:{plan_id:p.plan_id,plan_version:p.plan_version,action_hash:p.action_hash,constraints_hash:p.constraints_hash,base_config_hash:p.base_config_hash,approved:true}})
    await command('apply')
  }
  return session
}

test('measured playback has one masked output and preserves the dropout',async({page})=>{
  await page.addInitScript(()=>{
    const audit={rawPlays:0,mask:null as {gapEnergy:number;outsideEnergy:number}|null}
    Object.assign(window,{soundAudit:audit})
    const raw=HTMLMediaElement.prototype.play
    HTMLMediaElement.prototype.play=function(){audit.rawPlays++;return raw.call(this)}
    const start=AudioBufferSourceNode.prototype.start
    AudioBufferSourceNode.prototype.start=function(...args:Parameters<typeof start>){
      if(this.buffer){
        const pcm=this.buffer.getChannelData(0),sr=this.buffer.sampleRate
        let gapEnergy=0,outsideEnergy=0
        for(let i=0;i<pcm.length;i++){if(i>=4.9*sr&&i<6.8*sr)gapEnergy+=Math.abs(pcm[i]);else outsideEnergy+=Math.abs(pcm[i])}
        audit.mask={gapEnergy,outsideEnergy}
      }
      return start.apply(this,args)
    }
  })
  const s=await sample(page)
  await page.goto(`/rehearsal/${s.id}#sound`)
  await page.getByRole('button',{name:'Play affected section',exact:true}).click()
  await expect.poll(()=>page.evaluate(()=>(window as unknown as {soundAudit:{mask:unknown}}).soundAudit.mask)).not.toBeNull()
  const audit=await page.evaluate(()=>(window as unknown as {soundAudit:{rawPlays:number;mask:{gapEnergy:number;outsideEnergy:number}}}).soundAudit)
  expect(audit.rawPlays).toBe(0)
  expect(audit.mask.gapEnergy).toBe(0)
  expect(audit.mask.outsideEnergy).toBeGreaterThan(1)
})

test('Before and After switch one audio source and show only the selected playhead',async({page})=>{
  await page.addInitScript(()=>{
    const active=new Set<AudioBufferSourceNode>()
    const audit={rawPlays:0,maxActive:0,starts:[] as {offset:number;gapEnergy:number}[]}
    Object.assign(window,{comparisonAudit:audit})
    const raw=HTMLMediaElement.prototype.play
    HTMLMediaElement.prototype.play=function(){audit.rawPlays++;return raw.call(this)}
    const start=AudioBufferSourceNode.prototype.start
    const stop=AudioBufferSourceNode.prototype.stop
    AudioBufferSourceNode.prototype.start=function(...args:Parameters<typeof start>){
      let gapEnergy=0
      if(this.buffer){
        const pcm=this.buffer.getChannelData(0),sr=this.buffer.sampleRate
        for(let i=Math.ceil(4.9*sr);i<6.8*sr;i++)gapEnergy+=Math.abs(pcm[i])
      }
      active.add(this);audit.maxActive=Math.max(audit.maxActive,active.size)
      audit.starts.push({offset:args[1]??0,gapEnergy})
      this.addEventListener('ended',()=>active.delete(this),{once:true})
      return start.apply(this,args)
    }
    AudioBufferSourceNode.prototype.stop=function(...args:Parameters<typeof stop>){active.delete(this);return stop.apply(this,args)}
  })
  const s=await sample(page,'a',true)
  await page.goto(`/rehearsal/${s.id}#compare`)
  const before=page.getByRole('slider',{name:'Before waveform',exact:true})
  const after=page.getByRole('slider',{name:'After waveform',exact:true})
  await before.focus();await page.keyboard.press('Home')
  for(let n=0;n<25;n++)await page.keyboard.press('ArrowRight')
  await page.getByRole('button',{name:'Play before take',exact:true}).click()
  await expect(page.getByRole('button',{name:'Pause before take',exact:true})).toBeVisible()
  await expect(before.locator('.waveform-playhead-line')).toHaveCount(1)
  await expect(after.locator('.waveform-playhead-line')).toHaveCount(0)
  await page.getByRole('button',{name:'Play after take',exact:true}).click()
  await expect(page.getByRole('button',{name:'Pause after take',exact:true})).toBeVisible()
  await expect(page.getByRole('button',{name:'Play before take',exact:true})).toBeVisible()
  await expect(before.locator('.waveform-playhead-line')).toHaveCount(0)
  await expect(after.locator('.waveform-playhead-line')).toHaveCount(1)
  const audit=await page.evaluate(()=>(window as unknown as {comparisonAudit:{rawPlays:number;maxActive:number;starts:{offset:number;gapEnergy:number}[]}}).comparisonAudit)
  expect(audit.rawPlays).toBe(0)
  expect(audit.maxActive).toBe(1)
  expect(audit.starts[0].gapEnergy).toBe(0)
  expect(audit.starts[1].gapEnergy).toBeGreaterThan(1)
  expect(audit.starts[1].offset).toBeGreaterThanOrEqual(audit.starts[0].offset)
  await page.getByRole('button',{name:'Marcus (Lead)',exact:true}).click()
  await expect(page.getByText(/Marcus.*no sound faults in either check/)).toBeVisible()
  await expect(page.getByRole('button',{name:/Compare Elena.*instead/})).toBeVisible()
  await page.getByRole('button',{name:'Play before take',exact:true}).click()
  await expect(page.getByRole('button',{name:'Pause before take',exact:true})).toBeVisible()
  await page.getByRole('button',{name:'Play after take',exact:true}).click()
  await expect(page.getByRole('button',{name:'Pause after take',exact:true})).toBeVisible()
  const healthy=await page.evaluate(()=>(window as unknown as {comparisonAudit:{maxActive:number;starts:{gapEnergy:number}[]}}).comparisonAudit)
  expect(healthy.maxActive).toBe(1)
  expect(healthy.starts.at(-2)!.gapEnergy).toBeGreaterThan(1)
  expect(healthy.starts.at(-1)!.gapEnergy).toBe(healthy.starts.at(-2)!.gapEnergy)
})

test('clipping stays clipping and does not become a fabricated missing interval',async({page})=>{
  const s=await sample(page,'c')
  await page.goto(`/rehearsal/${s.id}#sound`)
  await expect(page.getByRole('table',{name:'Microphone issue status'})).toContainText(/clipp/i)
  await expect(page.getByRole('table',{name:'Microphone issue status'})).not.toContainText('1.9s missing')
})

test('a preview report remains inconclusive and does not claim Grafana verified it',async({page})=>{
  const s=await sample(page,'a',true)
  await page.goto(`/reports/${s.id}`)
  await expect(page.getByRole('heading',{name:'Check report',exact:true})).toBeVisible()
  await expect(page.getByText(/Inconclusive \(preview/)).toBeVisible()
  await expect(page.getByRole('link',{name:/Open readings in Grafana/})).toHaveCount(0)
  const downloaded=page.waitForEvent('download')
  await page.getByRole('button',{name:'Download report',exact:true}).click()
  const file=await downloaded
  const stream=await file.createReadStream()
  const chunks=[]
  for await(const chunk of stream!)chunks.push(chunk)
  const body=JSON.parse(Buffer.concat(chunks).toString())
  expect(body.mode).toBe('preview')
  expect(body.verification.terminal_status).toBe('INCONCLUSIVE')
  expect(body.csrf_token).toBeUndefined()
  expect(body.grafana_links).toEqual([])
})

test('a healthy rehearsal skips change approval and never invents an after take',async({page})=>{
  const s=await sample(page,'control')
  const response=await page.request.post(`/api/sessions/${s.id}/investigate`,{headers:{'X-CSRF-Token':s.csrf_token},data:{revision:s.revision}})
  expect(response.ok()).toBe(true)
  expect((await response.json()).state).toBe('NO_RISK')
  await page.goto(`/rehearsal/${s.id}`)
  await expect(page.getByRole('heading',{name:'Check report',exact:true})).toBeVisible()
  await expect(page.getByRole('button',{name:/Step 4: Compare/})).toBeDisabled()
  await expect(page.getByRole('img',{name:'After mini waveform',exact:true})).toHaveCount(0)
  await expect(page.getByText('You approved',{exact:true})).toHaveCount(0)
  await expect(page.getByText('Thresholds exceeded',{exact:true})).toHaveCount(0)
})
