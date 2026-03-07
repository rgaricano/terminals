<script>
	import { fetchConfig } from '$lib/apis/config.js';
	import { onMount } from 'svelte';

	let config = $state(null);
	let loading = $state(true);
	let error = $state('');

	onMount(async () => {
		try {
			config = await fetchConfig();
		} catch (e) {
			error = e.message;
		} finally {
			loading = false;
		}
	});
</script>

<div class="p-10 max-w-4xl">
	<h1 class="text-xl font-semibold tracking-tight mb-1">Settings</h1>
	<p class="text-[13px] text-muted mb-8">Runtime configuration (read-only)</p>

	{#if loading}
		<p class="text-[13px] text-muted">Loading...</p>
	{:else if error}
		<p class="text-[13px] text-red-400">{error}</p>
	{:else if config}
		<div class="space-y-6">
			<!-- General -->
			<section>
				<h2 class="text-[12px] text-muted uppercase tracking-widest mb-3">General</h2>
				<div class="rounded-xl border border-border overflow-hidden divide-y divide-border">
					{#each [
						{ label: 'Backend', value: config.backend },
						{ label: 'Host', value: config.host },
						{ label: 'Port', value: config.port },
						{ label: 'Data Directory', value: config.data_dir },
					] as row}
						<div class="flex justify-between px-5 py-3 text-[13px]">
							<span class="text-muted">{row.label}</span>
							<span class="font-mono">{row.value}</span>
						</div>
					{/each}
				</div>
			</section>

			<!-- Docker -->
			{#if config.backend === 'docker'}
				<section>
					<h2 class="text-[12px] text-muted uppercase tracking-widest mb-3">Docker</h2>
					<div class="rounded-xl border border-border overflow-hidden divide-y divide-border">
						{#each [
							{ label: 'Image', value: config.image },
							{ label: 'Network', value: config.network || 'default' },
						] as row}
							<div class="flex justify-between px-5 py-3 text-[13px]">
								<span class="text-muted">{row.label}</span>
								<span class="font-mono">{row.value}</span>
							</div>
						{/each}
					</div>
				</section>
			{/if}

			<!-- Kubernetes -->
			{#if config.backend === 'kubernetes' || config.backend === 'kubernetes-operator'}
				<section>
					<h2 class="text-[12px] text-muted uppercase tracking-widest mb-3">Kubernetes</h2>
					<div class="rounded-xl border border-border overflow-hidden divide-y divide-border">
						{#each [
							{ label: 'Namespace', value: config.kubernetes_namespace },
							{ label: 'Image', value: config.kubernetes_image },
							{ label: 'Storage Class', value: config.kubernetes_storage_class || 'default' },
							{ label: 'Storage Size', value: config.kubernetes_storage_size },
							{ label: 'Service Type', value: config.kubernetes_service_type },
						] as row}
							<div class="flex justify-between px-5 py-3 text-[13px]">
								<span class="text-muted">{row.label}</span>
								<span class="font-mono">{row.value}</span>
							</div>
						{/each}
					</div>
				</section>
			{/if}

			<!-- Lifecycle -->
			<section>
				<h2 class="text-[12px] text-muted uppercase tracking-widest mb-3">Lifecycle</h2>
				<div class="rounded-xl border border-border overflow-hidden divide-y divide-border">
					{#each [
						{ label: 'Idle Timeout', value: `${config.idle_timeout_seconds}s (${Math.round(config.idle_timeout_seconds / 60)}min)` },
						{ label: 'Cleanup Interval', value: `${config.cleanup_interval_seconds}s` },
					] as row}
						<div class="flex justify-between px-5 py-3 text-[13px]">
							<span class="text-muted">{row.label}</span>
							<span class="font-mono">{row.value}</span>
						</div>
					{/each}
				</div>
			</section>

			<!-- Auth -->
			<section>
				<h2 class="text-[12px] text-muted uppercase tracking-widest mb-3">Auth & Integrations</h2>
				<div class="rounded-xl border border-border overflow-hidden divide-y divide-border">
					{#each [
						{ label: 'API Key', value: config.has_api_key ? 'Configured' : 'Not set' },
						{ label: 'Open WebUI', value: config.has_open_webui_url ? 'Configured' : 'Not set' },
						{ label: 'SIEM Webhook', value: config.has_siem_webhook ? 'Configured' : 'Not set' },
					] as row}
						<div class="flex justify-between px-5 py-3 text-[13px]">
							<span class="text-muted">{row.label}</span>
							<span class="{row.value === 'Configured' ? 'text-green-400' : 'text-muted'}">{row.value}</span>
						</div>
					{/each}
				</div>
			</section>
		</div>
	{/if}
</div>
