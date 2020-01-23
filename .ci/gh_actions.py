#!/usr/bin/env python3

import importlib.util
import os
import subprocess
import sys

import git
import github

# Try to import, but its not critical
libnames = ['bot_jokes']
for libname in libnames:
    try:
        lib = __import__(libname)
    except Exception:
        print(sys.exc_info())
    else:
        globals()[libname] = lib

PWD = os.path.dirname(os.path.abspath(__file__))
GIT_DEFAULT_BRANCH = 'master'
PR_MESSAGE_BODY = os.path.join(PWD, 'pr_body.md')


def import_create_dockerfiles(location_dir):
    """Import the dockerfile generation script"""
    location = os.path.join(location_dir, 'create_dockerfiles.py')
    spec = importlib.util.spec_from_file_location(
        name='create.dockerfiles', location=location)
    create_dockerfiles = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(create_dockerfiles)
    return create_dockerfiles


def import_create_dockerlibrary(location_dir):
    """Import the dockerlibrary generation script"""
    location = os.path.join(location_dir, 'create_dockerlibrary.py')
    spec = importlib.util.spec_from_file_location(
        name='create.dockerlibrary', location=location)
    create_dockerlibrary = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(create_dockerlibrary)
    return create_dockerlibrary


def test_diffs(diffs):
    """Check the diffs, also print them and fail the test if they exist"""
    if diffs:
        for diff in diffs:
            print(diff)
        raise ValueError('Autogenerated files are not up to date')


def test_builds(hub_tag_dir):
    """Check make build completes for the given repo tag directory"""
    command = ['make', 'build']
    with subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            cwd=hub_tag_dir,
            bufsize=1,
            universal_newlines=True) as p:
        for line in p.stdout:
            print(line, end='')  # process line here

    if p.returncode != 0:
        raise subprocess.CalledProcessError(p.returncode, p.args)


def main(argv=sys.argv[1:]):
    """Check travis context and trigger docker builds"""

    # Public environment variables, available for pull requests from forks
    HUB_REPO = os.environ['HUB_REPO']
    HUB_RELEASE = os.environ['HUB_RELEASE']
    HUB_OS_NAME = os.environ['HUB_OS_NAME']
    HUB_OS_CODE_NAME = os.environ['HUB_OS_CODE_NAME']
    GIT_BRANCH = os.environ['GITHUB_BASE_REF']
    GIT_PULL_REQUEST_BRANCH = os.environ['GITHUB_HEAD_REF']
    GIT_UPSTREAM_REPO_SLUG = os.environ['GITHUB_REPOSITORY']
    GIT_BUILD_DIR = os.environ['GITHUB_WORKSPACE']
    GITHUB_EVENT_NAME = os.environ['GITHUB_EVENT_NAME']

    print("HUB_REPO: ", HUB_REPO)
    print("HUB_RELEASE: ", HUB_RELEASE)
    print("HUB_OS_NAME: ", HUB_OS_NAME)
    print("HUB_OS_CODE_NAME: ", HUB_OS_CODE_NAME)
    print("GIT_UPSTREAM_REPO_SLUG: ", GIT_UPSTREAM_REPO_SLUG)
    print("GIT_BRANCH: ", GIT_BRANCH)
    print("GITHUB_EVENT_NAME: ", GITHUB_EVENT_NAME)
    print("GIT_PULL_REQUEST_BRANCH: ", GIT_PULL_REQUEST_BRANCH)

    # Private environment variables, not available for pull requests from forks
    GIT_USER = os.environ.get('GITHUB_USER', '')
    GIT_EMAIL = os.environ.get('GITHUB_EMAIL', '')
    GIT_TOKEN = os.environ.get('GITHUB_TOKEN', '')
    GIT_AUTHOR = "{user} <{email}>".format(user=GIT_USER, email=GIT_EMAIL)
    GIT_ORIGIN_REPO_SLUG = GIT_USER + '/' + \
        GIT_UPSTREAM_REPO_SLUG.split('/')[1]
    GIT_REMOTE_ORIGIN_TOKEN_URL = "https://{user}:{token}@github.com/{repo_slug}.git".format(
        user=GIT_USER,
        token=GIT_TOKEN,
        repo_slug=GIT_ORIGIN_REPO_SLUG
    )

    # Initialize git interfaces
    repo = git.Repo(GIT_BUILD_DIR, odbt=git.GitCmdObjectDB)

    # Expand the repo:tag directory
    hub_repo_dir = os.path.join(GIT_BUILD_DIR, HUB_REPO)
    hub_tag_dir = os.path.join(
        hub_repo_dir, HUB_RELEASE, HUB_OS_NAME, HUB_OS_CODE_NAME)

    # Try updating the Dockerfiles
    create_dockerfiles = import_create_dockerfiles(hub_repo_dir)
    create_dockerfiles.main(('dir', '-d' + hub_tag_dir))

    # Create diff for the current repo
    diffs = repo.index.diff(None, create_patch=True)

    # Check if this is PR or Cron job test
    # if GITHUB_EVENT_NAME == 'pull_request':
    if GITHUB_EVENT_NAME == 'garbage':
        # If this is a PR test
        print("Testing Pull Request for Branch: ", GIT_PULL_REQUEST_BRANCH)

        # Test that dockerfile generation has changed nothing
        # and that all dockerfiles are up to date
        test_diffs(diffs)

        target = repo.branches[GIT_BRANCH].commit
        pull_request = repo.head.commit
        pr_diffs = target.diff(pull_request, paths=[hub_tag_dir])

        if pr_diffs:
            # Test that the dockerfiles build
            test_builds(hub_tag_dir)

    else:
        # If this is a test from CronJob or push
        print("Testing Branch: ", GIT_BRANCH)

        try:
            # Test that dockerfile generation has changed nothing
            # and that all dockerfiles are up to date
            test_diffs(diffs)
        except ValueError:
            # If there are changes, only proceed for the default branch
            if GIT_BRANCH == GIT_DEFAULT_BRANCH:
                print("GIT_BRANCH is default branch, proceeding...")
                # Initialize github interfaces
                g = github.Github(login_or_token=GIT_TOKEN)
                g_origin_repo = g.get_repo(
                    full_name_or_id=GIT_ORIGIN_REPO_SLUG)
                g_upstream_repo = g.get_repo(
                    full_name_or_id=GIT_UPSTREAM_REPO_SLUG)

                # Define common attributes for new PR
                pr_branch_name = (
                    '/').join([HUB_REPO, HUB_RELEASE, HUB_OS_NAME, HUB_OS_CODE_NAME])
                pr_head_name = GIT_USER + ':' + pr_branch_name

                pr_remote = git.remote.Remote(repo=repo, name='origin')
                pr_remote.add(repo=repo, name='upstream_pr',
                              url=GIT_REMOTE_ORIGIN_TOKEN_URL)

                # Commit changes to Dockerfiles
                repo.git.add(all=True)
                message = "Updating Dockerfiles\n" + \
                    "This is an automated CI commit"
                repo.git.commit(m=message, author=GIT_AUTHOR)

                # Update the Docker Library
                manifest = os.path.join(hub_repo_dir, 'manifest.yaml')
                output = os.path.join(hub_repo_dir, HUB_REPO)
                create_dockerlibrary = import_create_dockerlibrary(
                    hub_repo_dir)
                create_dockerlibrary.main((
                    '--manifest', manifest,
                    '--output', output))

                # Commit changes to Docker Library
                repo.git.add(all=True)
                message = "Updating Docker Library\n" + \
                    "This is an automated CI commit"
                repo.git.commit(m=message, author=GIT_AUTHOR)

                # Create new branch from current head
                pr_branch_head = repo.create_head(pr_branch_name)  # noqa

                # Check if branch exists remotely
                try:
                    g_branch = g_origin_repo.get_branch(branch=pr_branch_name)  # noqa
                except github.GithubException as exception:
                    if exception.data['message'] == "Branch not found":
                        pr_branch_exists = False
                    else:
                        raise
                else:
                    pr_branch_exists = True

                if pr_branch_exists:
                    # Try fource pushing if remote branch already exists
                    try:
                        repo.git.push(
                            'upstream_pr', pr_branch_name + ':' + pr_branch_name, force=True)
                    except Exception as inst:
                        inst.stderr = None
                        raise ValueError(
                            ("Force push to branch:{branch} failed! "
                             "Stderr omitted to protect secrets.").format(branch=pr_branch_name))
                else:
                    # Otherwise try setting up the remote upsteam branch
                    try:
                        repo.git.push(
                            'upstream_pr', pr_branch_name + ':' + pr_branch_name, u=True)
                    except Exception as inst:
                        inst.stderr = None
                        raise ValueError(
                            ("Set-upstream push to branch:{branch} failed! "
                             "Stderr omitted to protect secrets.").format(branch=pr_branch_name))

                # Add some commentary for new PR
                title = "Updating {}".format(pr_branch_name)
                with open(PR_MESSAGE_BODY, 'r') as f:
                    body = f.read()
                try:
                    body += bot_jokes.get_bot_joke()
                except Exception:
                    pass

                # Get github pull for upstream
                g_pulls = g_upstream_repo.get_pulls(
                    state='open',
                    sort='created',
                    base=GIT_BRANCH,
                    head=pr_head_name)

                # Check if PR already exists
                if g_pulls.get_page(0):
                    raise ValueError(
                        ("Relevant PR from {pr_head_name} "
                         "is already open.").format(pr_head_name=pr_head_name))
                else:
                    # Create new PR for remote banch
                    g_upstream_repo.create_pull(
                        title=title,
                        body=body,
                        base=GIT_BRANCH,
                        head=pr_head_name)
                    raise ValueError(
                        ("Relevant PR from {pr_head_name} "
                         "has been created.").format(pr_head_name=pr_head_name))
            raise

        # Test that the dockerfiles build
        test_builds(hub_tag_dir)


if __name__ == '__main__':
    main()
