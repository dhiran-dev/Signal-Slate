import {test,expect,type Page,type Locator} from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

async function audit(page:Page){
  const results=await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21aa']).analyze()
  expect(results.violations).toEqual([])
}
async function keyboardActivate(page:Page,target:Locator,key='Enter'){
  await expect(target).toBeVisible();await expect(target).toBeEnabled()
  for(let i=0;i<120;i++){
    await page.keyboard.press('Tab')
    if(await target.evaluate(el=>el===document.activeElement)){await page.keyboard.press(key);return}
  }
  throw Error('Keyboard could not reach '+await target.innerText())
}
const button=(page:Page,name:string)=>page.getByRole('button',{name,exact:true})
async function choosePreview(page:Page){
  await keyboardActivate(page,page.locator('.connection-help-summary'))
  await keyboardActivate(page,page.getByRole('radio',{name:'Live cloud check',exact:true}),'ArrowDown')
  await expect(page.getByRole('radio',{name:'Preview without cloud',exact:true})).toBeChecked()
}
async function confirmRule(page:Page){
  const input=page.getByRole('textbox',{name:'Channels to keep free',exact:true})
  await keyboardActivate(page,input)
  await input.press('ControlOrMeta+A');await input.pressSequentially('Exclude channel 11')
  await keyboardActivate(page,button(page,'Interpret rule'))
  await keyboardActivate(page,button(page,'Confirm rule'))
  await keyboardActivate(page,button(page,'Test this change'))
  await expect(page.getByRole('heading',{name:'Compare takes',exact:true})).toBeVisible()
}
for(const width of [390,768,1440])test(`keyboard rehearsal and WCAG at ${width}px`,async({page})=>{
  test.setTimeout(90000);page.setDefaultTimeout(10000)
  await page.setViewportSize({width,height:900});await page.emulateMedia({reducedMotion:'reduce'})
  await page.goto('/');await audit(page)
  await page.goto('/rehearsal');await audit(page)
  await choosePreview(page)
  await keyboardActivate(page,button(page,'Check sound'))
  await expect(page.getByRole('heading',{name:'Sound issues',exact:true})).toBeVisible()
  await keyboardActivate(page,button(page,'Mute sound'))
  await expect(button(page,'Unmute sound')).toBeVisible()
  await keyboardActivate(page,button(page,'Play affected section'))
  await keyboardActivate(page,button(page,'Pause affected section'))
  const soundSlider=page.getByRole('slider').first()
  await soundSlider.press('Home');for(let i=0;i<25;i++)await soundSlider.press('ArrowRight')
  await expect(page.getByLabel('Synchronized caption',{exact:true})).toBeVisible()
  await expect(page.getByLabel('Synchronized caption',{exact:true})).toContainText('Simulated silence')
  await audit(page)
  await keyboardActivate(page,button(page,'Find a fix'))
  await expect(page.getByRole('heading',{name:'Review change',exact:true})).toBeVisible()
  await confirmRule(page);await audit(page)
  const beforeSlider=page.getByRole('slider',{name:'Before waveform',exact:true})
  await beforeSlider.press('Home');for(let i=0;i<25;i++)await beforeSlider.press('ArrowRight')
  await keyboardActivate(page,button(page,'Play after take'))
  await keyboardActivate(page,button(page,'Pause after take'))
  await expect(page.getByLabel('Synchronized caption',{exact:true})).not.toContainText('Simulated silence')
  await keyboardActivate(page,button(page,'Play before take'))
  await expect(page.getByLabel('Synchronized caption',{exact:true})).toContainText('Simulated silence')
  await keyboardActivate(page,button(page,'Pause before take'))
  await keyboardActivate(page,button(page,'View report'))
  await expect(page.getByRole('heading',{name:'Check report',exact:true})).toBeVisible();await audit(page)
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
  const download=page.waitForEvent('download');await keyboardActivate(page,button(page,'Download report'))
  expect((await download).suggestedFilename()).toBe('signal-slate-report.json')
})

for(const preset of ['b','c','control'])test(`blind case ${preset} preserves mechanism and controls`,async({page})=>{
  page.setDefaultTimeout(10000)
  await page.goto('/rehearsal');await page.getByRole('combobox',{name:'Sample scene',exact:true}).selectOption(preset)
  await choosePreview(page);await button(page,'Check sound').click()
  await expect(page.getByRole('heading',{name:'Sound issues',exact:true})).toBeVisible()
  if(preset==='control'){
    await button(page,'View report').click()
    await expect(page.getByText('No issues found · All checks normal',{exact:true})).toBeVisible()
    await expect(button(page,'Interpret rule')).toHaveCount(0);await expect(button(page,'Test this change')).toHaveCount(0)
    return
  }
  await button(page,'Find a fix').click();await confirmRule(page)
  const table=page.getByRole('table',{name:'Before and after comparison table',exact:true})
  await expect(table).toContainText(preset==='b'?'Antenna B':'Overhead Boom backup')
  await expect(page.getByRole('heading',{name:'Compare takes',exact:true})).toBeVisible()
  await audit(page)
})
