# Changelog

## [2.0.2](https://github.com/Ryther/hapatchy/compare/v2.0.1...v2.0.2) (2026-10-07)


### Bug Fixes

* preserve patch health after unrelated YAML edits ([b6c42c0](https://github.com/Ryther/hapatchy/commit/b6c42c084bad11dee134c2e4ad8edec647787f2b))

## [2.0.1](https://github.com/Ryther/hapatchy/compare/v2.0.0...v2.0.1) (2026-10-01)


### Bug Fixes

* clear watch repairs after verified recovery ([7c55057](https://github.com/Ryther/hapatchy/commit/7c55057b94a90ebe1e19b4de4906748a4fdfee8a))

## [2.0.0](https://github.com/Ryther/hapatchy/compare/v1.0.7...v2.0.0) (2026-09-30)


### ⚠ BREAKING CHANGES

* **compat:** HAPatchY now requires Home Assistant 2026.7.4 and Python 3.14.2 or newer.

### Bug Fixes

* **compat:** require Home Assistant 2026.7.4 ([009918b](https://github.com/Ryther/hapatchy/commit/009918b4c76f7f967b6e24f30e54a5e080ddeffd))


### Documentation

* align compatibility guidance with the new HA minimum ([8788328](https://github.com/Ryther/hapatchy/commit/8788328f95b179c564d80370421f52b6045df754))

## [1.0.7](https://github.com/Ryther/hapatchy/compare/v1.0.6...v1.0.7) (2026-09-29)


### Bug Fixes

* **brand:** add unified banner to public guides ([#79](https://github.com/Ryther/hapatchy/issues/79)) ([5b41fb2](https://github.com/Ryther/hapatchy/commit/5b41fb272f2f67e710cd72ed46a3e8e0e731e3c9))

## [1.0.6](https://github.com/Ryther/hapatchy/compare/v1.0.5...v1.0.6) (2026-09-29)


### Bug Fixes

* **brand:** use bordered HAPatchY icons ([#77](https://github.com/Ryther/hapatchy/issues/77)) ([7c19796](https://github.com/Ryther/hapatchy/commit/7c19796661a6a3b69ba96bbefcb311aa26ae0f03))

## [1.0.5](https://github.com/Ryther/hapatchy/compare/v1.0.4...v1.0.5) (2026-09-29)


### Bug Fixes

* **config-flow:** recover native setup and patch retries ([#75](https://github.com/Ryther/hapatchy/issues/75)) ([0d9a490](https://github.com/Ryther/hapatchy/commit/0d9a4907e915e7544c36b6f0b220f50307621150))

## [1.0.4](https://github.com/Ryther/hapatchy/compare/v1.0.3...v1.0.4) (2026-09-28)


### Bug Fixes

* **ci:** avoid repushing unchanged HA proposals ([#69](https://github.com/Ryther/hapatchy/issues/69)) ([a37d186](https://github.com/Ryther/hapatchy/commit/a37d1860ec07deabfa3344bb411c468b94d41796))
* **ci:** decode GitHub content and skip blocked candidates ([#67](https://github.com/Ryther/hapatchy/issues/67)) ([d657645](https://github.com/Ryther/hapatchy/commit/d657645ef3bf25a1fdbca0f910a5eb3a66d13124))
* **ci:** derive recent HA test version from locked pins ([#65](https://github.com/Ryther/hapatchy/issues/65)) ([8791b8d](https://github.com/Ryther/hapatchy/commit/8791b8db0fb486c2973af9fd5cc526c922a1dccf))
* **ci:** distinguish missing HA branch from API error body ([#64](https://github.com/Ryther/hapatchy/issues/64)) ([c830137](https://github.com/Ryther/hapatchy/commit/c830137ff561c9d228008a36ceaea4ccd633cf56))
* **ci:** gate advisories on product requirements only ([#73](https://github.com/Ryther/hapatchy/issues/73)) ([78746f8](https://github.com/Ryther/hapatchy/commit/78746f860a7a2e82b4df7db7330f637ae6a91388))
* **ci:** inspect public branch summary for auto-merge ([#63](https://github.com/Ryther/hapatchy/issues/63)) ([85538aa](https://github.com/Ryther/hapatchy/commit/85538aa5f92a6ebba486d324c8328bbc07dc8f06))
* **ci:** mount absolute Sonar report path in Docker ([86ab19d](https://github.com/Ryther/hapatchy/commit/86ab19dfa0241dedfafa5b0122283c4e57916577))
* **ci:** report advisory gate success on main ([#60](https://github.com/Ryther/hapatchy/issues/60)) ([7707220](https://github.com/Ryther/hapatchy/commit/770722084a03351d25a2374234a6c1a3bb7e3a4f))
* **ci:** report inherited HA lock advisories without blocking ([07d049a](https://github.com/Ryther/hapatchy/commit/07d049a3c5413df8317d69a73ad32e5e182a4f51))
* **ci:** scope product analysis to shipped integration ([#74](https://github.com/Ryther/hapatchy/issues/74)) ([d827183](https://github.com/Ryther/hapatchy/commit/d82718376c228faa30a0164fc511aa706113c48e))
* **ci:** wait for eventual editor sensor in HA smoke ([ef45463](https://github.com/Ryther/hapatchy/commit/ef454634aabf16b1c491bbe79682621535ad6637))
* **compat:** validate Home Assistant 2026.9.4 ([03469f0](https://github.com/Ryther/hapatchy/commit/03469f072607122099dfd46cfae20f47de0d9fc6))


### Documentation

* add task-oriented documentation navigation ([43cf753](https://github.com/Ryther/hapatchy/commit/43cf7531ab16e5a69026de159b351aee0cf38652))
* build and publish navigable site ([e5fb812](https://github.com/Ryther/hapatchy/commit/e5fb8122329051487bbc048659d8b241099a33ec))
* define documentation impact and reading contracts ([453d4e7](https://github.com/Ryther/hapatchy/commit/453d4e70581c25c45f3fdb08d4112b14ab47340e))
* keep screenshot label independent of HA baseline ([125fbb5](https://github.com/Ryther/hapatchy/commit/125fbb5a80764b619e5ca91531f32dae72e7a42a))
* make README useful in HACS ([f26cb23](https://github.com/Ryther/hapatchy/commit/f26cb233df1674738c383a26f072ea0e191aec47))
* require HACS-ready README reviews ([34cd6f2](https://github.com/Ryther/hapatchy/commit/34cd6f215836a3b023207fbe54a18696092c0ae9))

## [1.0.3](https://github.com/Ryther/hapatchy/compare/v1.0.2...v1.0.3) (2026-09-28)


### Bug Fixes

* block releases on unresolved Sonar security findings ([#49](https://github.com/Ryther/hapatchy/issues/49)) ([d4f1ef8](https://github.com/Ryther/hapatchy/commit/d4f1ef87eb1df9118e2d01d4d11b98ef34d990e9))
* retry locked CI installs after package index failures ([#51](https://github.com/Ryther/hapatchy/issues/51)) ([bf4d8fc](https://github.com/Ryther/hapatchy/commit/bf4d8fce48396cf764a52261f5f3a4140449076b))

## [1.0.2](https://github.com/Ryther/hapatchy/compare/v1.0.1...v1.0.2) (2026-09-28)


### Bug Fixes

* stabilize Sonar PR analysis and integration boundaries ([#47](https://github.com/Ryther/hapatchy/issues/47)) ([c01606a](https://github.com/Ryther/hapatchy/commit/c01606a40faf0a445a10612cc427bb354577aca6))

## [1.0.1](https://github.com/Ryther/hapatchy/compare/v1.0.0...v1.0.1) (2026-09-27)


### Bug Fixes

* render repository documentation in HACS ([77c02f8](https://github.com/Ryther/hapatchy/commit/77c02f8b8638d6faf2bc22d552dac752aff17fde))

## [1.0.0](https://github.com/Ryther/hapatchy/compare/v0.4.1...v1.0.0) (2026-09-25)


### Bug Fixes

* report unknown patch health before checks ([9e3bac9](https://github.com/Ryther/hapatchy/commit/9e3bac997e5bd82e0815f0d492a1033a2a474ba6))


### Documentation

* define 1.0 compatibility contract ([627f2e7](https://github.com/Ryther/hapatchy/commit/627f2e71ebcd755d0666f9b30d98b294a5455c5a))

## [0.4.1](https://github.com/Ryther/hapatchy/compare/v0.4.0...v0.4.1) (2026-09-25)


### Bug Fixes

* name problem entity patch health ([b44a69a](https://github.com/Ryther/hapatchy/commit/b44a69a42d820836eadfcb7873be472b56543c16))


### Documentation

* show patch health states in the device guide ([7de397e](https://github.com/Ryther/hapatchy/commit/7de397e30051871383ed823588664e5bcbad1090))

## [0.4.0](https://github.com/Ryther/hapatchy/compare/v0.3.1...v0.4.0) (2026-09-25)


### Features

* group patches as devices with on-demand diff inspection ([81a0f74](https://github.com/Ryther/hapatchy/commit/81a0f7450ec9a5543696aea2965277673f9baced))


### Bug Fixes

* show file editor errors and support 512 KiB files ([142c2a5](https://github.com/Ryther/hapatchy/commit/142c2a510a4a9d715608d7a59079a82463221035))


### Documentation

* explain editor limits and validation errors ([7cff88f](https://github.com/Ryther/hapatchy/commit/7cff88f3b9cc203f8c9cbc770344bc2d6717e45c))
* explain patch devices, diff inspection, and editor limits ([778e91e](https://github.com/Ryther/hapatchy/commit/778e91e8fa45d9a8d0b1ea9e217480e03ff02bb8))

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
