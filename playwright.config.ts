import {defineConfig} from '@playwright/test'
export default defineConfig({testDir:'./tests/e2e',fullyParallel:false,workers:1,retries:0,reporter:'list',use:{baseURL:process.env.BROWSER_BASE_URL||'http://localhost:5173',headless:true,launchOptions:{args:['--mute-audio']},trace:'retain-on-failure'},outputDir:'test-results'})
