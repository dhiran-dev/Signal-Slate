import React from 'react'
import { LandingPage } from './landing/LandingPage'
import { Rehearsal } from './rehearsal/Rehearsal'

export const App: React.FC = () => {
  if (/^\/rehearsal(?:\/[^/]+)?$/.test(window.location.pathname)) return <Rehearsal />
  if (/^\/reports?(?:\/[^/]+)?$/.test(window.location.pathname)) return <Rehearsal report />
  return <LandingPage />
}

export default App
