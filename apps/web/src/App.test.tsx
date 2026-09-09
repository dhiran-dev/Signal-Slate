import { render, screen } from '@testing-library/react'
import { describe, it, expect, beforeEach, vi } from 'vitest'
import App from './App'

describe('Signal Slate Landing Page & Application Routing', () => {
  beforeEach(() => {
    window.history.replaceState(null, '', '/')
    window.HTMLMediaElement.prototype.play = vi.fn().mockResolvedValue(undefined)
    window.HTMLMediaElement.prototype.pause = vi.fn()
    // Mock matchMedia
    window.matchMedia = vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn()
    }))
  })

  describe('Landing Page Structure & Approved Content', () => {
    it('renders Signal Slate brand, approved headline, and subhead', () => {
      render(<App />)

      // Brand
      expect(screen.getAllByText('Signal Slate').length).toBeGreaterThanOrEqual(1)

      // Approved headline (exactly matching reference)
      expect(
        screen.getByRole('heading', {
          level: 1,
          name: /Check the sound\s*before the next take\./i
        })
      ).toBeInTheDocument()

      // Approved subhead
      expect(
        screen.getByText(
          'For film sound teams: catch a microphone cutting out during an important line. Review a suggested setting change, then check whether the next rehearsal improves.'
        )
      ).toBeInTheDocument()
    })

    it('renders honest simulation disclosure without cloud runtime claims', () => {
      render(<App />)

      expect(
        screen.getByText('Sample scene · Simulated microphone readings')
      ).toBeInTheDocument()

      // Does not contain obsolete project or dev jargon
      expect(screen.queryByText(/balmy-coral/i)).not.toBeInTheDocument()
      expect(screen.queryByText(/Phase 4 Prototype/i)).not.toBeInTheDocument()
    })

    it('renders the approved primary and secondary calls to action', () => {
      render(<App />)

      const primaryCta = screen.getByRole('link', { name: /Start a sound check/i })
      expect(primaryCta).toBeInTheDocument()
      expect(primaryCta).toHaveAttribute('href', '/rehearsal')

      const howItWorks = screen.getByRole('link', { name: /See how it works/i })
      expect(howItWorks).toBeInTheDocument()
      expect(howItWorks).toHaveAttribute('href', '#how-it-works')
    })

    it('renders the 3-step walkthrough strip with approved steps and imagery', () => {
      render(<App />)

      expect(
        screen.getByRole('heading', {
          level: 2,
          name: /Choose a scene\.\s*Check the sound\.\s*Review the result\./i
        })
      ).toBeInTheDocument()

      expect(screen.getByText('Choose a scene')).toBeInTheDocument()
      expect(screen.getByText('Check the sound')).toBeInTheDocument()
      expect(screen.getByText('Review the result')).toBeInTheDocument()

      // First step uses supplied alleyway scene image
      const sceneImg = screen.getByAltText(/Alleyway scene showing street/i)
      expect(sceneImg).toBeInTheDocument()
      expect(sceneImg).toHaveAttribute('src', '/images/alleyway-scene.png')
    })

    it('renders hero desk artwork', () => {
      render(<App />)

      const heroImg = screen.getByAltText(/Cinema sound desk with mixer/i)
      expect(heroImg).toBeInTheDocument()
      expect(heroImg).toHaveAttribute('src', '/images/sound-desk.png')
    })
  })

  describe('Routing', () => {
    it('routes to rehearsal workflow when location is /rehearsal', async () => {
      window.history.replaceState(null, '', '/rehearsal')
      render(<App />)

      // Rehearsal header & setup screen
      expect(await screen.findByRole('heading', { level: 1, name: 'Scene setup' })).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Check sound' })).toBeInTheDocument()
    })

    it('routes to rehearsal report when location is /report', async () => {
      window.history.replaceState(null, '', '/report')
      render(<App />)

      expect(await screen.findByRole('heading', { level: 1, name: 'Check report' })).toBeInTheDocument()
    })
  })
})
