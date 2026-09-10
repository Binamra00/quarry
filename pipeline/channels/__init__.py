"""
Trigger channel sources: fetching the TEXT in which triggers are expressed.

This module holds the source contract and its implementations, nothing else -- the same shape as
adapters/ and commands/. Supporting machinery lives in utils/: channel_state for resumable
progress, github_client for API transport.

A channel is one source of developer discourse -- commit messages, issues, pull requests, PR
review comments, issue comments. Each source normalises its platform's raw shape into one
unified record, so a downstream detector can scan records without knowing where they came from.

Sources supply raw TEXT and the structural facts only the platform can report. They do not
detect triggers, do not extract references, and do not resolve files -- each is recomputable
from the mined records, and none should require re-mining to change.

    i_sources        the contract: IChannelSource, the unified record, RateLimitExhausted
    git_sources      the local repository
    github_sources   the GitHub REST API
"""
from pipeline.channels.i_sources import IChannelSource, RateLimitExhausted, blank_record
from pipeline.channels.git_sources import GitCommitSource
from pipeline.channels.github_sources import GITHUB_SOURCES

__all__ = [
    "IChannelSource", "RateLimitExhausted", "blank_record",
    "GitCommitSource", "GITHUB_SOURCES",
]