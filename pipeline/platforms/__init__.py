"""
Platform transport: how to reach each external system.

One module per value the CLI's --platform flag accepts. A platform module knows HOW to talk to
its system -- run a git command, page through a REST API -- and nothing about WHY. The channel
sources above decide what to ask for; these decide how to ask.

    --platform git     ->  channels/git_sources.py     ->  git_gateway, git_client
    --platform github  ->  channels/github_sources.py  ->  github_client

    git_gateway     git plumbing: rev-list, cat-file, merge-base, rev-parse
    git_client      cloning, with progress streamed rather than captured
    github_client   GitHub REST: auth, pagination, primary and secondary rate limits

NO SHARED CONTRACT, DELIBERATELY. Running a subprocess against a local repository and paging
through an HTTP API have no method in common:

    GitGateway.run(args)              -> (ok, output)
    GitHubClient.paginate(endpoint)   -> Iterator[(page, items)]

An i_platform interface over those would declare nothing. This is a feature module, like scope/
and state/ -- the convention that a module holds only a contract and its implementations applies
to modules that HAVE a contract, such as channels/ and adapters/.

BOTTOM LAYER. Nothing here imports from the domain modules above it. Where a platform needs to
signal something the domain cares about -- an exhausted API quota -- it raises its own transport
exception, and the source translates it into the channel contract's equivalent.
"""
from pipeline.platforms.git_gateway import GitGateway
from pipeline.platforms.git_client import GitClient
from pipeline.platforms.github_client import (
    GitHubClient, GitHubAccessError, GitHubRateLimited,
)

__all__ = [
    "GitGateway", "GitClient",
    "GitHubClient", "GitHubAccessError", "GitHubRateLimited",
]