import {test,expect} from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

test('all six guided pages remain accessible without horizontal overflow at phone, tablet and desktop sizes',async({page})=>{
  test.setTimeout(120000)
  let s=await(await page.request.post('/api/sessions',{data:{mode:'preview',preset:'a'}})).json()
  async function command(action:string,extra:Record<string,unknown>={}){
    const r=await page.request.post(`/api/sessions/${s.id}/${action}`,{headers:{'X-CSRF-Token':s.csrf_token},data:{revision:s.revision,...extra}})
    expect(r.ok()).toBe(true);s=await r.json();expect(s.error).toBeNull()
  }
  await command('baseline');await command('investigate');await command('constraints',{text:'Exclude channel 11'});await command('confirm',{constraints:s.interpretation.constraints.map((c:Record<string,unknown>)=>({...c,confirmed:true}))})
  const p=s.candidate_plans[0]
  await command('approve',{approval:{plan_id:p.plan_id,plan_version:p.plan_version,action_hash:p.action_hash,constraints_hash:p.constraints_hash,base_config_hash:p.base_config_hash,approved:true}});await command('apply')
  const pages=[['/','Check the sound'],['/rehearsal','Scene setup'],[`/rehearsal/${s.id}#sound`,'Sound issues'],[`/rehearsal/${s.id}#change`,'Review change'],[`/rehearsal/${s.id}#compare`,'Compare takes'],[`/reports/${s.id}`,'Check report']]
  for(const width of [390,768,1440,1536])for(const [url,title] of pages){
    await test.step(`${title} at ${width}px`,async()=>{
      await page.setViewportSize({width,height:1024})
      await page.goto(url);await page.reload()
      await expect(page.getByRole('heading',{name:new RegExp(title)}).first()).toBeVisible()
      expect.soft(await page.evaluate(()=>document.documentElement.scrollWidth-window.innerWidth),`${title} ${width}px overflow`).toBeLessThanOrEqual(1)
      const result=await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21aa']).analyze()
      expect.soft(result.violations.map(v=>({id:v.id,impact:v.impact,nodes:v.nodes.map(n=>({target:n.target,summary:n.failureSummary}))})),`${title} ${width}px accessibility`).toEqual([])
    })
  }
})
