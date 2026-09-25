# Changelog

## [0.3.1](https://github.com/Ryther/hapatchy/compare/v0.3.0...v0.3.1) (2026-09-25)


### Performance Improvements

* accelerate YAML source verification ([#27](https://github.com/Ryther/hapatchy/issues/27)) ([fcd6ad8](https://github.com/Ryther/hapatchy/commit/fcd6ad86ae372c2ca976f26560951f969541ab80))


### Documentation

* schedule review of Dependabot exclusions ([e3e5e37](https://github.com/Ryther/hapatchy/commit/e3e5e37f4a62e0d9ea244222a81bd1f82bd44875))

## [0.3.0](https://github.com/Ryther/hapatchy/compare/v0.2.1...v0.3.0) (2026-09-25)


### Features

* build exact patches from edited text ([143c70e](https://github.com/Ryther/hapatchy/commit/143c70e404598c1c6a042b47d6887e12531b2c71))
* create managed patches from file edits ([b32507d](https://github.com/Ryther/hapatchy/commit/b32507d9fb0496b24fccc3047abb16e50e3dbf96))
* read editable targets through guarded policy ([3466be3](https://github.com/Ryther/hapatchy/commit/3466be3cd5392632b1c9e5a4e463dd9ae3f78b9d))


### Bug Fixes

* preserve edits after recoverable editor errors ([938d376](https://github.com/Ryther/hapatchy/commit/938d37699a4ff1f97de87f750286b091fd07ba8c))
* recheck file and grants while saving editor patch ([249ec0e](https://github.com/Ryther/hapatchy/commit/249ec0ecf7c51f64eb772f0dd8353d784b43df37))
* require generated patches to reverse exactly ([e37b964](https://github.com/Ryther/hapatchy/commit/e37b964fa733cc4acd6358a8fcd20084c4f1d639))


### Documentation

* explain how to create a patch file ([857b176](https://github.com/Ryther/hapatchy/commit/857b176f7812d330dc047a68d57fa3a3b509d4f0))
* guide users through native file editing ([424ec03](https://github.com/Ryther/hapatchy/commit/424ec038ac4244a4f9e86cbfc5fbb5c0bcc6051f))

## [0.2.1](https://github.com/Ryther/hapatchy/compare/v0.2.0...v0.2.1) (2026-09-24)


### Bug Fixes

* avoid repeated YAML scans in patch picker ([f3ab9fa](https://github.com/Ryther/hapatchy/commit/f3ab9fa61973264bce696cfcefc86847996c39f3))
* close YAML include directory descriptors ([499fd57](https://github.com/Ryther/hapatchy/commit/499fd578fb6fab1c4d5f8f423940c3c3035eefe5))


### Documentation

* add HACS custom repository button ([d7f5e0b](https://github.com/Ryther/hapatchy/commit/d7f5e0bda07b051308eaa9f3aa38b2537068e25a))

## 0.2.0 (2026-09-24)

Initial public release.

### Features

* implement safe single-file patch engine and transactions ([59deb7e](https://github.com/Ryther/hapatchy/commit/59deb7e119acd2f38fff76d3596a7e0ba00ca2c1))
* integrate patch management with native Home Assistant APIs ([099d315](https://github.com/Ryther/hapatchy/commit/099d3152f11408dbdf14ed75680b6b98fed46592))
* require frozen YAML directory grants for patch operations ([c08b186](https://github.com/Ryther/hapatchy/commit/c08b186c6da250da91caccfa5fb1c400fa4fef2e))
* **storage:** persist immutable managed patch sources ([e2c1a47](https://github.com/Ryther/hapatchy/commit/e2c1a47cb458f70201456b348f69ff6740a0a09c))
* **ui:** add patch editor, uploads and target file selection ([eaef7a6](https://github.com/Ryther/hapatchy/commit/eaef7a63b43ed57d9bc29d04bc2cd4cda15244d6))


### Bug Fixes

* **ci:** exempt release-only manifest version from UX review ([d559f67](https://github.com/Ryther/hapatchy/commit/d559f675c40a3fa528499644e80b1b42f9183a4a))
* **security:** close HTTPS resolver and clarify legacy recovery ([cd0451b](https://github.com/Ryther/hapatchy/commit/cd0451b6f6c129d874670ce0ab20d59bf0882898))
* **security:** restrict HTTPS patch sources to public DNS answers ([3c1326d](https://github.com/Ryther/hapatchy/commit/3c1326dfa2ff801f1bc4d846b39a36c3237f7d2a))


### Documentation

* add portable HAPatchY user skill ([451e77f](https://github.com/Ryther/hapatchy/commit/451e77f6a25fa82e3674fa5d88f9c11498e1bdb3))
* align public guides with verified YAML authorization ([095555c](https://github.com/Ryther/hapatchy/commit/095555c7a4df688b035882c93651413742c10c80))
* define repository guidance for AI contributors ([5a499aa](https://github.com/Ryther/hapatchy/commit/5a499aaa8912e7a46b303b07600bc9be5743f525))
* document verified managed patch workflows ([8a21bd9](https://github.com/Ryther/hapatchy/commit/8a21bd9a9b9436ec3151b4b930f0d687215abad1))
* document vibecoded provenance and release validation ([eca5139](https://github.com/Ryther/hapatchy/commit/eca5139bdc480cbb762fd009f0c81509042d0771))
* guide users through installation, patching and recovery ([32cf1e0](https://github.com/Ryther/hapatchy/commit/32cf1e06ac970df3e3ed719682d6bd4e734ad1ec))
* make HAPatchY user skill self-contained ([36ff7c9](https://github.com/Ryther/hapatchy/commit/36ff7c964da8705bed4f38fee23653d3f32db4f0))
* record public HACS validation and hosted tests ([34376f4](https://github.com/Ryther/hapatchy/commit/34376f4b14cb84ba082ea5ec698ebca609d12236))
* remove private project references from agent guide ([76fd32d](https://github.com/Ryther/hapatchy/commit/76fd32de9d0414c59825d76224b69fdb3042f070))
* require Dev Container reproduction for PR problems ([4ff7a7f](https://github.com/Ryther/hapatchy/commit/4ff7a7f43a3dd654cbb151509deb60f5fae4bf0d))
* require user guides and skill updates for UX changes ([a1ca9f9](https://github.com/Ryther/hapatchy/commit/a1ca9f9d80f647aae8692187a712ae24b35f27b5))
* verify first patch walkthrough in disposable HA ([1176bf3](https://github.com/Ryther/hapatchy/commit/1176bf3b7c1447a4379569022e4bd60ce4f56d1a))
* verify user procedures in HA and clarify the release flow ([6e4dbd0](https://github.com/Ryther/hapatchy/commit/6e4dbd02089a2d35ce030bafdb23174b05f3b0c6))
