import {readFile} from 'node:fs/promises'
import openapiTS, {astToString} from 'openapi-typescript'
const generated=astToString(await openapiTS(new URL('../contracts/openapi.json',import.meta.url)))
const actual=await readFile(new URL('../apps/web/src/api.generated.ts',import.meta.url),'utf8')
// The CLI adds a fixed generated-file warning; compare the generated type body exactly.
const body=actual.slice(actual.indexOf('export '))
if(body!==generated.slice(generated.indexOf('export '))){console.error('Generated API types drifted. Run npm run contracts:generate.');process.exit(1)}
console.log('Generated API types match the frozen OpenAPI schema.')
