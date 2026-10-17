import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  // signal-flow.js is vendored verbatim from redhawkliger/signal-flow so it can
  // be re-synced by copying the file. Linting third-party code we don't edit
  // would mean patching it on every sync (it currently trips no-unused-vars).
  // Scoped to that one file — bridge.css and SignalFlowHero.jsx in the same
  // folder are ours and stay linted.
  globalIgnores(['dist', 'src/lib/signal-flow/signal-flow.js']),
  {
    files: ['**/*.{js,jsx}'],
    extends: [
      js.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      globals: globals.browser,
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
  },
])
