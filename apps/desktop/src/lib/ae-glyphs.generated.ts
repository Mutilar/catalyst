// GENERATED from quine/canon/GLYPH.json; do not edit.

const TOKENS = {"category.hats":"🎩","category.mechanisms":"🎼","delimiter.segment":" · ","hat.accessibility":"♿","hat.ai-agent":"🦾","hat.architecture":"📐","hat.cross-surface":"🌐","hat.design":"🎨","hat.observability":"📊","hat.performance":"⚡","hat.security":"🔒","hat.testability":"🧪","hat.tooling":"🔧","identity.android-shell":"📱","identity.butler":"🤖","identity.catalyst":"🚀","identity.envelope":"✉️","identity.genui":"🔮","identity.linux-shell":"🐚","identity.lucid":"🧠","identity.macos-shell":"💻","identity.maintainer-console":"🛠️","identity.marketplace":"🛍️","identity.parakeet":"🦜","identity.penguin":"🐧","identity.plexus":"🌐","identity.plexus-service":"📡","identity.plexus-service-path":"🛰️","identity.projects":"🧩","identity.quine":"🧬","identity.repo-maintenance":"🔧","identity.run":"🔥","identity.shell-host":"💻","identity.shells":"🖥️","identity.site":"🌐","identity.speech":"🎤","identity.store":"📮","identity.ugui":"🖼️","identity.windows-shell":"🪟","operation.cancel":"⛔","operation.dispatch":"🚀","operation.get":"🔎","operation.morph":"🧬","operation.set":"✏️","operation.show":"🖼️","operation.steer":"🧭","relation.action":"➡️","relation.argument":"⚙️","relation.datum":"◆","relation.evidence":"🔎","relation.noun":"🎯","relation.timing":"⏳","relation.verb":"⚡","role.butler":"🎩","role.em":"🎼","role.engineer":"🦾","role.penguin":"🐧","role.sidekick":"🧭","signal.green":"🟢","signal.pending":"⏳","signal.red":"🔴","signal.warning":"⚠️"} as const
const MARKER = /\[\[([a-z0-9.-]+)\]\]/g

export type GlyphRole = keyof typeof TOKENS

export function glyph(role: GlyphRole): string {
  return TOKENS[role]
}

export function glyphText(template: string): string {
  return template.replace(MARKER, (_match, role: string) => {
    if (!(role in TOKENS)) {throw new Error(`unknown GLYPH role: ${role}`)}

    return glyph(role as GlyphRole)
  })
}

export const CATEGORY_HATS = TOKENS["category.hats"]
export const CATEGORY_MECHANISMS = TOKENS["category.mechanisms"]
export const DELIMITER_SEGMENT = TOKENS["delimiter.segment"]
export const HAT_ACCESSIBILITY = TOKENS["hat.accessibility"]
export const HAT_AI_AGENT = TOKENS["hat.ai-agent"]
export const HAT_ARCHITECTURE = TOKENS["hat.architecture"]
export const HAT_CROSS_SURFACE = TOKENS["hat.cross-surface"]
export const HAT_DESIGN = TOKENS["hat.design"]
export const HAT_OBSERVABILITY = TOKENS["hat.observability"]
export const HAT_PERFORMANCE = TOKENS["hat.performance"]
export const HAT_SECURITY = TOKENS["hat.security"]
export const HAT_TESTABILITY = TOKENS["hat.testability"]
export const HAT_TOOLING = TOKENS["hat.tooling"]
export const IDENTITY_ANDROID_SHELL = TOKENS["identity.android-shell"]
export const IDENTITY_BUTLER = TOKENS["identity.butler"]
export const IDENTITY_CATALYST = TOKENS["identity.catalyst"]
export const IDENTITY_ENVELOPE = TOKENS["identity.envelope"]
export const IDENTITY_GENUI = TOKENS["identity.genui"]
export const IDENTITY_LINUX_SHELL = TOKENS["identity.linux-shell"]
export const IDENTITY_LUCID = TOKENS["identity.lucid"]
export const IDENTITY_MACOS_SHELL = TOKENS["identity.macos-shell"]
export const IDENTITY_MAINTAINER_CONSOLE = TOKENS["identity.maintainer-console"]
export const IDENTITY_MARKETPLACE = TOKENS["identity.marketplace"]
export const IDENTITY_PARAKEET = TOKENS["identity.parakeet"]
export const IDENTITY_PENGUIN = TOKENS["identity.penguin"]
export const IDENTITY_PLEXUS = TOKENS["identity.plexus"]
export const IDENTITY_PLEXUS_SERVICE = TOKENS["identity.plexus-service"]
export const IDENTITY_PLEXUS_SERVICE_PATH = TOKENS["identity.plexus-service-path"]
export const IDENTITY_PROJECTS = TOKENS["identity.projects"]
export const IDENTITY_QUINE = TOKENS["identity.quine"]
export const IDENTITY_REPO_MAINTENANCE = TOKENS["identity.repo-maintenance"]
export const IDENTITY_RUN = TOKENS["identity.run"]
export const IDENTITY_SHELL_HOST = TOKENS["identity.shell-host"]
export const IDENTITY_SHELLS = TOKENS["identity.shells"]
export const IDENTITY_SITE = TOKENS["identity.site"]
export const IDENTITY_SPEECH = TOKENS["identity.speech"]
export const IDENTITY_STORE = TOKENS["identity.store"]
export const IDENTITY_UGUI = TOKENS["identity.ugui"]
export const IDENTITY_WINDOWS_SHELL = TOKENS["identity.windows-shell"]
export const OPERATION_CANCEL = TOKENS["operation.cancel"]
export const OPERATION_DISPATCH = TOKENS["operation.dispatch"]
export const OPERATION_GET = TOKENS["operation.get"]
export const OPERATION_MORPH = TOKENS["operation.morph"]
export const OPERATION_SET = TOKENS["operation.set"]
export const OPERATION_SHOW = TOKENS["operation.show"]
export const OPERATION_STEER = TOKENS["operation.steer"]
export const RELATION_ACTION = TOKENS["relation.action"]
export const RELATION_ARGUMENT = TOKENS["relation.argument"]
export const RELATION_DATUM = TOKENS["relation.datum"]
export const RELATION_EVIDENCE = TOKENS["relation.evidence"]
export const RELATION_NOUN = TOKENS["relation.noun"]
export const RELATION_TIMING = TOKENS["relation.timing"]
export const RELATION_VERB = TOKENS["relation.verb"]
export const ROLE_BUTLER = TOKENS["role.butler"]
export const ROLE_EM = TOKENS["role.em"]
export const ROLE_ENGINEER = TOKENS["role.engineer"]
export const ROLE_PENGUIN = TOKENS["role.penguin"]
export const ROLE_SIDEKICK = TOKENS["role.sidekick"]
export const SIGNAL_GREEN = TOKENS["signal.green"]
export const SIGNAL_PENDING = TOKENS["signal.pending"]
export const SIGNAL_RED = TOKENS["signal.red"]
export const SIGNAL_WARNING = TOKENS["signal.warning"]
