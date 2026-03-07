<script>
	import { signinOpenWebUI } from '$lib/apis/openwebui.js';
	import { saveOpenWebUIAuth, saveApiKeyAuth } from '$lib/auth.js';

	let mode = $state('open-webui'); // 'open-webui' | 'api-key'
	let openWebUIUrl = $state('');
	let email = $state('');
	let password = $state('');
	let apiKey = $state('');
	let loading = $state(false);
	let error = $state('');

	async function handleOpenWebUI(e) {
		e.preventDefault();
		loading = true;
		error = '';
		try {
			const url = openWebUIUrl.replace(/\/+$/, '');
			const res = await signinOpenWebUI(url, email, password);
			saveOpenWebUIAuth(url, res.token, {
				id: res.id,
				email: res.email,
				name: res.name,
				role: res.role,
				profile_image_url: res.profile_image_url
			});
			window.location.href = '/';
		} catch (e) {
			error = e.message;
		} finally {
			loading = false;
		}
	}

	function handleApiKey(e) {
		e.preventDefault();
		if (!apiKey.trim()) return;
		saveApiKeyAuth(apiKey.trim());
		window.location.href = '/';
	}
</script>

<div class="min-h-screen flex items-center justify-center">
	<div class="w-full max-w-sm">
		<h1 class="text-lg font-semibold tracking-tight mb-1">Terminals</h1>
		<p class="text-[13px] text-muted mb-8">Connect to manage terminal instances.</p>

		<!-- Mode selector -->
		<div class="flex gap-1 mb-6 bg-subtle rounded-lg p-1">
			<button
				class="flex-1 text-[13px] py-1.5 rounded-md transition-colors {mode === 'open-webui' ? 'bg-panel text-white' : 'text-muted hover:text-white'}"
				onclick={() => (mode = 'open-webui')}
			>Open WebUI</button>
			<button
				class="flex-1 text-[13px] py-1.5 rounded-md transition-colors {mode === 'api-key' ? 'bg-panel text-white' : 'text-muted hover:text-white'}"
				onclick={() => (mode = 'api-key')}
			>API Key</button>
		</div>

		{#if error}
			<div class="mb-4 text-[13px] text-red-400">{error}</div>
		{/if}

		{#if mode === 'open-webui'}
			<form onsubmit={handleOpenWebUI} class="space-y-3">
				<div>
					<label for="url" class="block text-[12px] text-muted mb-1">Open WebUI URL</label>
					<input id="url" type="url" bind:value={openWebUIUrl} placeholder="https://your-openwebui.com" required
						class="w-full px-3 py-2 text-[13px] bg-surface border border-border rounded-lg text-white placeholder:text-muted/40 focus:outline-none focus:border-white/20 transition-colors" />
				</div>
				<div>
					<label for="email" class="block text-[12px] text-muted mb-1">Email</label>
					<input id="email" type="email" bind:value={email} placeholder="you@example.com" required
						class="w-full px-3 py-2 text-[13px] bg-surface border border-border rounded-lg text-white placeholder:text-muted/40 focus:outline-none focus:border-white/20 transition-colors" />
				</div>
				<div>
					<label for="password" class="block text-[12px] text-muted mb-1">Password</label>
					<input id="password" type="password" bind:value={password} required
						class="w-full px-3 py-2 text-[13px] bg-surface border border-border rounded-lg text-white placeholder:text-muted/40 focus:outline-none focus:border-white/20 transition-colors" />
				</div>
				<button type="submit" disabled={loading} class="w-full mt-2 px-4 py-2 text-[13px] font-medium bg-white text-black rounded-lg hover:bg-white/90 transition-colors disabled:opacity-30">
					{loading ? 'Signing in...' : 'Sign in'}
				</button>
			</form>
		{:else}
			<form onsubmit={handleApiKey} class="space-y-3">
				<div>
					<label for="key" class="block text-[12px] text-muted mb-1">API Key</label>
					<input id="key" type="password" bind:value={apiKey} placeholder="TERMINALS_API_KEY" required
						class="w-full px-3 py-2 text-[13px] bg-surface border border-border rounded-lg text-white placeholder:text-muted/40 focus:outline-none focus:border-white/20 transition-colors" />
				</div>
				<button type="submit" class="w-full mt-2 px-4 py-2 text-[13px] font-medium bg-white text-black rounded-lg hover:bg-white/90 transition-colors">
					Connect
				</button>
			</form>
		{/if}
	</div>
</div>
