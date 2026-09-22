"""GENERATED from quine/canon/GLYPH.json; do not edit."""

from __future__ import annotations

import re

_TOKENS = {"category.hats":"🎩","category.mechanisms":"🎼","delimiter.segment":" · ","hat.accessibility":"♿","hat.ai-agent":"🦾","hat.architecture":"📐","hat.cross-surface":"🌐","hat.design":"🎨","hat.observability":"📊","hat.performance":"⚡","hat.security":"🔒","hat.testability":"🧪","hat.tooling":"🔧","identity.android-shell":"📱","identity.butler":"🤖","identity.catalyst":"🚀","identity.envelope":"✉️","identity.genui":"🔮","identity.keystone":"🪨","identity.linux-shell":"🐚","identity.lucid":"🧠","identity.macos-shell":"💻","identity.maintainer-console":"🛠️","identity.marketplace":"🛍️","identity.parakeet":"🦜","identity.penguin":"🐧","identity.plexus":"📡","identity.plexus-service":"🛰️","identity.projects":"🧩","identity.quine":"🧬","identity.repo-maintenance":"🔧","identity.run":"🔥","identity.shell-host":"💻","identity.shells":"🖥️","identity.site":"🌐","identity.speech":"🎤","identity.store":"📮","identity.ugui":"🖼️","identity.windows-shell":"🪟","operation.cancel":"⛔","operation.copy":"⧉","operation.dispatch":"🚀","operation.get":"🔎","operation.morph":"🧬","operation.set":"✏️","operation.show":"🖼️","operation.steer":"🧭","relation.action":"➡️","relation.argument":"⚙️","relation.datum":"ℹ️","relation.evidence":"🔎","relation.noun":"🎯","relation.timing":"⏳","relation.verb":"⚡","role.butler":"🎩","role.em":"🎼","role.engineer":"🦾","role.penguin":"🐧","role.sidekick":"🧭","signal.green":"🟢","signal.pending":"⏳","signal.red":"🔴","signal.warning":"⚠️"}
_MARKER = re.compile(r"\[\[([a-z0-9.-]+)\]\]")

def glyph(role: str) -> str:
    try:
        return _TOKENS[role]
    except KeyError as error:
        raise ValueError(f"unknown GLYPH role: {role}") from error

def glyph_text(template: str) -> str:
    return _MARKER.sub(lambda match: glyph(match.group(1)), template)

CATEGORY_HATS = glyph('category.hats')
CATEGORY_MECHANISMS = glyph('category.mechanisms')
DELIMITER_SEGMENT = glyph('delimiter.segment')
HAT_ACCESSIBILITY = glyph('hat.accessibility')
HAT_AI_AGENT = glyph('hat.ai-agent')
HAT_ARCHITECTURE = glyph('hat.architecture')
HAT_CROSS_SURFACE = glyph('hat.cross-surface')
HAT_DESIGN = glyph('hat.design')
HAT_OBSERVABILITY = glyph('hat.observability')
HAT_PERFORMANCE = glyph('hat.performance')
HAT_SECURITY = glyph('hat.security')
HAT_TESTABILITY = glyph('hat.testability')
HAT_TOOLING = glyph('hat.tooling')
IDENTITY_ANDROID_SHELL = glyph('identity.android-shell')
IDENTITY_BUTLER = glyph('identity.butler')
IDENTITY_CATALYST = glyph('identity.catalyst')
IDENTITY_ENVELOPE = glyph('identity.envelope')
IDENTITY_GENUI = glyph('identity.genui')
IDENTITY_KEYSTONE = glyph('identity.keystone')
IDENTITY_LINUX_SHELL = glyph('identity.linux-shell')
IDENTITY_LUCID = glyph('identity.lucid')
IDENTITY_MACOS_SHELL = glyph('identity.macos-shell')
IDENTITY_MAINTAINER_CONSOLE = glyph('identity.maintainer-console')
IDENTITY_MARKETPLACE = glyph('identity.marketplace')
IDENTITY_PARAKEET = glyph('identity.parakeet')
IDENTITY_PENGUIN = glyph('identity.penguin')
IDENTITY_PLEXUS = glyph('identity.plexus')
IDENTITY_PLEXUS_SERVICE = glyph('identity.plexus-service')
IDENTITY_PROJECTS = glyph('identity.projects')
IDENTITY_QUINE = glyph('identity.quine')
IDENTITY_REPO_MAINTENANCE = glyph('identity.repo-maintenance')
IDENTITY_RUN = glyph('identity.run')
IDENTITY_SHELL_HOST = glyph('identity.shell-host')
IDENTITY_SHELLS = glyph('identity.shells')
IDENTITY_SITE = glyph('identity.site')
IDENTITY_SPEECH = glyph('identity.speech')
IDENTITY_STORE = glyph('identity.store')
IDENTITY_UGUI = glyph('identity.ugui')
IDENTITY_WINDOWS_SHELL = glyph('identity.windows-shell')
OPERATION_CANCEL = glyph('operation.cancel')
OPERATION_COPY = glyph('operation.copy')
OPERATION_DISPATCH = glyph('operation.dispatch')
OPERATION_GET = glyph('operation.get')
OPERATION_MORPH = glyph('operation.morph')
OPERATION_SET = glyph('operation.set')
OPERATION_SHOW = glyph('operation.show')
OPERATION_STEER = glyph('operation.steer')
RELATION_ACTION = glyph('relation.action')
RELATION_ARGUMENT = glyph('relation.argument')
RELATION_DATUM = glyph('relation.datum')
RELATION_EVIDENCE = glyph('relation.evidence')
RELATION_NOUN = glyph('relation.noun')
RELATION_TIMING = glyph('relation.timing')
RELATION_VERB = glyph('relation.verb')
ROLE_BUTLER = glyph('role.butler')
ROLE_EM = glyph('role.em')
ROLE_ENGINEER = glyph('role.engineer')
ROLE_PENGUIN = glyph('role.penguin')
ROLE_SIDEKICK = glyph('role.sidekick')
SIGNAL_GREEN = glyph('signal.green')
SIGNAL_PENDING = glyph('signal.pending')
SIGNAL_RED = glyph('signal.red')
SIGNAL_WARNING = glyph('signal.warning')
