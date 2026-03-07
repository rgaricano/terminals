<script>
	import '../app.css';
	import { isAuthenticated, getUser, getAuthMode, clearAuth } from '$lib/auth.js';
	import { healthCheck } from '$lib/apis/health.js';
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';

	let { children } = $props();
	let ready = $state(false);
	let user = $state(null);
	let authMode = $state(null);
	let healthy = $state(null);

	onMount(() => {
		const path = window.location.pathname;
		const authed = isAuthenticated();

		if (!authed && path !== '/login') {
			goto('/login');
		} else if (authed && path === '/login') {
			goto('/');
		}

		user = getUser();
		authMode = getAuthMode();
		ready = true;

		if (authed) {
			checkHealth();
			const interval = setInterval(checkHealth, 30000);
			return () => clearInterval(interval);
		}
	});

	async function checkHealth() {
		try {
			const res = await healthCheck();
			healthy = res.status === true;
		} catch {
			healthy = false;
		}
	}

	function logout() {
		clearAuth();
		goto('/login');
	}

	function isActive(path) {
		return $page.url.pathname === path;
	}
</script>

{#if !ready}
	<div class="min-h-screen"></div>
{:else if $page.url.pathname === '/login'}
	{@render children()}
{:else}
	<div class="flex h-screen">
		<aside class="w-52 shrink-0 border-r border-border flex flex-col">
			<div class="p-5">
				<h1 class="text-sm font-semibold tracking-tight">Terminals</h1>
			</div>
			<nav class="flex-1 px-3 space-y-0.5">
				<a href="/" class="flex items-center gap-2 px-3 py-1.5 text-[13px] rounded-md transition-colors {isActive('/') ? 'text-white bg-white/[0.06]' : 'text-muted hover:text-white'}">
					Dashboard
				</a>
				<a href="/settings" class="flex items-center gap-2 px-3 py-1.5 text-[13px] rounded-md transition-colors {isActive('/settings') ? 'text-white bg-white/[0.06]' : 'text-muted hover:text-white'}">
					Settings
				</a>
			</nav>
			<div class="px-4 py-3 border-t border-border space-y-2">
				<div class="flex items-center gap-1.5">
					{#if healthy === null}
						<span class="w-1.5 h-1.5 rounded-full bg-muted"></span>
						<span class="text-[11px] text-muted">Checking...</span>
					{:else if healthy}
						<span class="w-1.5 h-1.5 rounded-full bg-green-400"></span>
						<span class="text-[11px] text-muted">Online</span>
					{:else}
						<span class="w-1.5 h-1.5 rounded-full bg-red-400"></span>
						<span class="text-[11px] text-muted">Offline</span>
					{/if}
				</div>
				{#if user}
					<div class="text-[12px] text-white truncate">{user.name}</div>
					<div class="text-[11px] text-muted truncate">{user.email}</div>
				{:else if authMode === 'api-key'}
					<div class="text-[11px] text-muted">API Key</div>
				{/if}
				<button onclick={logout} class="text-[11px] text-muted hover:text-white transition-colors">Sign out</button>
			</div>
		</aside>
		<main class="flex-1 overflow-y-auto">
			{@render children()}
		</main>
	</div>
{/if}
