# Changelog

## [2026-11-02]

- fix: substitui seletores legados quebrados (`StyledStatisticBox`, `?tab=completed-rooms`, `?tab=badges`) por pipeline resiliente em 3 camadas (API Pública v2 HTTP → API v2 via Chromium Playwright → DOM Next.js atualizado)
- fix: elimina `KeyError: 'username'` e `thumbnail: {}` inválido no envio ao Webhook do Discord quando a coleta falha ou o avatar está ausente
- sec: remove URL de Webhook hardcoded do código-fonte e adiciona suporte a `.env`, variáveis de ambiente, argumentos CLI e prompt interativo
- feat: adiciona instalação automática de bibliotecas ausentes (`requests`, `playwright`) e download sob demanda do binário Chromium
- feat: escrita JSON atômica (`tmp + os.replace`), `requirements.txt`, suite de 14 testes automatizados e `README.md` padronizado
