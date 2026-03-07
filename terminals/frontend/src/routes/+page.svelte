<script>
	import { fetchTenants, createTenant, deleteTenant, startTenant, stopTenant } from '$lib/apis/tenants.js';
	import { fetchStats } from '$lib/apis/config.js';
	import { onMount } from 'svelte';

	let tenants = $state([]);
	let stats = $state({ total: 0, running: 0, stopped: 0, error: 0, active_ws_connections: 0 });
	let loading = $state(true);
	let error = $state('');
	let showModal = $state(false);
	let userId = $state('');
	let provisioning = $state(false);
	let provisionError = $state('');
	let actionId = $state(null); // user_id currently being acted on
	let search = $state('');
	let statusFilter = $state('all');
	let expandedId = $state(null);
	let idleTimeout = $state(0);

	let filtered = $derived(() => {
		let list = tenants;
		if (statusFilter !== 'all') {
			list = list.filter(t => t.status === statusFilter);
		}
		if (search.trim()) {
			const q = search.toLowerCase();
			list = list.filter(t => t.user_id.toLowerCase().includes(q) || (t.instance_name || '').toLowerCase().includes(q));
		}
		return list;
	});

	async function load() {
		try {
			[tenants, stats] = await Promise.all([fetchTenants(), fetchStats()]);
			error = '';
		} catch (e) {
			error = e.message;
		} finally {
			loading = false;
		}
	}

	async function provision() {
		if (!userId.trim()) return;
		provisioning = true; provisionError = '';
		try { await createTenant(userId.trim()); showModal = false; userId = ''; await load(); }
		catch (e) { provisionError = e.message; }
		finally { provisioning = false; }
	}

	async function remove(id) {
		actionId = id;
		try { await deleteTenant(id); await load(); }
		catch (e) { error = e.message; }
		finally { actionId = null; }
	}

	async function start(id) {
		actionId = id;
		try { await startTenant(id); await load(); }
		catch (e) { error = e.message; }
		finally { actionId = null; }
	}

	async function stop(id) {
		actionId = id;
		try { await stopTenant(id); await load(); }
		catch (e) { error = e.message; }
		finally { actionId = null; }
	}

	function ago(ts) {
		if (!ts) return '-';
		const d = Date.now() - new Date(ts).getTime();
		if (d < 60000) return 'now';
		if (d < 3600000) return `${Math.floor(d / 60000)}m`;
		if (d < 86400000) return `${Math.floor(d / 3600000)}h`;
		return new Date(ts).toLocaleDateString('en', { month: 'short', day: 'numeric' });
	}

	function idlePercent(ts) {
		if (!ts || !idleTimeout) return 0;
		const elapsed = (Date.now() - new Date(ts).getTime()) / 1000;
		return Math.min(100, Math.round((elapsed / idleTimeout) * 100));
	}

	onMount(async () => {
		await load();
		// Fetch idle timeout from config
		try {
			const { fetchConfig } = await import('$lib/apis/config.js');
			const cfg = await fetchConfig();
			idleTimeout = cfg.idle_timeout_seconds || 0;
		} catch {}
		const interval = setInterval(load, 15000);
		return () => clearInterval(interval);
	});
</script>

<div class="p-10 max-w-6xl">
	<!-- Header -->
	<div class="flex items-center justify-between mb-10">
		<h1 class="text-xl font-semibold tracking-tight">Dashboard</h1>
		<button onclick={() => (showModal = true)} class="text-[13px] px-4 py-2 bg-white text-black rounded-lg font-medium hover:bg-white/90 transition-colors">
			New Tenant
		</button>
	</div>

	<!-- Stats -->
	<div class="grid grid-cols-5 gap-px bg-border rounded-xl overflow-hidden mb-8">
		{#each [
			{ label: 'Total', value: stats.total },
			{ label: 'Running', value: stats.running },
			{ label: 'Stopped', value: stats.stopped },
			{ label: 'Errors', value: stats.error },
			{ label: 'WS Connections', value: stats.active_ws_connections }
		] as s}
			<div class="bg-panel p-5">
				<div class="text-2xl font-semibold tracking-tight">{s.value}</div>
				<div class="text-[11px] text-muted mt-1 uppercase tracking-widest">{s.label}</div>
			</div>
		{/each}
	</div>

	<!-- Error -->
	{#if error}
		<div class="mb-6 text-[13px] text-red-400 bg-red-400/5 border border-red-400/10 rounded-lg px-4 py-3 flex justify-between items-center">
			{error}
			<button onclick={() => (error = '')} class="text-red-400/40 hover:text-red-400 ml-4">x</button>
		</div>
	{/if}

	<!-- Table -->
	<div class="rounded-xl border border-border overflow-hidden">
		<div class="flex items-center justify-between px-5 py-3 border-b border-border">
			<!-- Status filter chips -->
			<div class="flex gap-1">
				{#each [
					{ key: 'all', label: 'All' },
					{ key: 'running', label: 'Running' },
					{ key: 'stopped', label: 'Stopped' },
					{ key: 'error', label: 'Error' }
				] as f}
					<button
						onclick={() => (statusFilter = f.key)}
						class="text-[12px] px-2.5 py-1 rounded-md transition-colors {statusFilter === f.key ? 'bg-white/[0.08] text-white' : 'text-muted hover:text-white'}"
					>{f.label}</button>
				{/each}
			</div>
			<input
				type="text"
				placeholder="Search"
				bind:value={search}
				class="text-[13px] bg-transparent border-none outline-none text-white placeholder:text-muted/40 w-40"
			/>
		</div>

		{#if loading}
			<div class="py-20 text-center text-[13px] text-muted">Loading...</div>
		{:else if filtered().length === 0}
			<div class="py-20 text-center">
				{#if search || statusFilter !== 'all'}
					<p class="text-[13px] text-muted">No results</p>
				{:else}
					<p class="text-[13px] text-muted mb-4">No tenants</p>
					<button onclick={() => (showModal = true)} class="text-[13px] px-4 py-2 bg-white text-black rounded-lg font-medium hover:bg-white/90 transition-colors">New Tenant</button>
				{/if}
			</div>
		{:else}
			<table class="w-full text-[13px]">
				<thead>
					<tr class="border-b border-border text-left text-muted">
						<th class="px-5 py-2.5 font-normal">User</th>
						<th class="px-5 py-2.5 font-normal">Status</th>
						<th class="px-5 py-2.5 font-normal">Backend</th>
						<th class="px-5 py-2.5 font-normal">Host</th>
						<th class="px-5 py-2.5 font-normal">Created</th>
						<th class="px-5 py-2.5 font-normal"></th>
					</tr>
				</thead>
				<tbody>
					{#each filtered() as t (t.id)}
						<!-- Main row -->
						<tr
							class="border-b border-border hover:bg-white/[0.02] transition-colors cursor-pointer {expandedId === t.id ? 'bg-white/[0.02]' : ''}"
							onclick={() => (expandedId = expandedId === t.id ? null : t.id)}
						>
							<td class="px-5 py-3 font-medium">{t.user_id}</td>
							<td class="px-5 py-3">
								<span class="inline-flex items-center gap-1.5">
									<span class="w-1.5 h-1.5 rounded-full {t.status === 'running' ? 'bg-green-400' : t.status === 'error' ? 'bg-red-400' : 'bg-yellow-400'}"></span>
									{t.status}
								</span>
							</td>
							<td class="px-5 py-3 text-muted">{t.backend_type}</td>
							<td class="px-5 py-3 text-muted font-mono text-xs">{t.host || '-'}:{t.port}</td>
							<td class="px-5 py-3 text-muted">{ago(t.created_at)}</td>
							<td class="px-5 py-3 text-right">
								<div class="inline-flex gap-2">
									{#if t.status === 'running'}
										<button
											onclick={(e) => { e.stopPropagation(); stop(t.user_id); }}
											disabled={actionId === t.user_id}
											class="text-muted hover:text-yellow-400 transition-colors disabled:opacity-30"
										>Stop</button>
									{:else if t.status === 'stopped'}
										<button
											onclick={(e) => { e.stopPropagation(); start(t.user_id); }}
											disabled={actionId === t.user_id}
											class="text-muted hover:text-green-400 transition-colors disabled:opacity-30"
										>Start</button>
									{/if}
									<button
										onclick={(e) => { e.stopPropagation(); remove(t.user_id); }}
										disabled={actionId === t.user_id}
										class="text-muted hover:text-red-400 transition-colors disabled:opacity-30"
									>Delete</button>
								</div>
							</td>
						</tr>
						<!-- Expanded detail row -->
						{#if expandedId === t.id}
							<tr class="border-b border-border bg-white/[0.01]">
								<td colspan="6" class="px-5 py-4">
									<div class="grid grid-cols-3 gap-4 text-[12px]">
										<div>
											<span class="text-muted">Instance ID</span>
											<div class="font-mono mt-0.5">{t.instance_id || '-'}</div>
										</div>
										<div>
											<span class="text-muted">Instance Name</span>
											<div class="font-mono mt-0.5">{t.instance_name || '-'}</div>
										</div>
										<div>
											<span class="text-muted">Port</span>
											<div class="mt-0.5">{t.port}</div>
										</div>
										<div>
											<span class="text-muted">Created</span>
											<div class="mt-0.5">{t.created_at ? new Date(t.created_at).toLocaleString() : '-'}</div>
										</div>
										<div>
											<span class="text-muted">Updated</span>
											<div class="mt-0.5">{t.updated_at ? new Date(t.updated_at).toLocaleString() : '-'}</div>
										</div>
										<div>
											<span class="text-muted">Last Accessed</span>
											<div class="mt-0.5">
												{t.last_accessed_at ? new Date(t.last_accessed_at).toLocaleString() : '-'}
												{#if t.status === 'running' && idleTimeout > 0 && t.last_accessed_at}
													{@const pct = idlePercent(t.last_accessed_at)}
													<div class="mt-1.5 flex items-center gap-2">
														<div class="flex-1 h-1 bg-border rounded-full overflow-hidden">
															<div class="h-full rounded-full transition-all {pct > 80 ? 'bg-red-400' : pct > 50 ? 'bg-yellow-400' : 'bg-green-400'}" style="width: {pct}%"></div>
														</div>
														<span class="text-[10px] text-muted">{pct}% idle</span>
													</div>
												{/if}
											</div>
										</div>
									</div>
								</td>
							</tr>
						{/if}
					{/each}
				</tbody>
			</table>
		{/if}
	</div>
</div>

<!-- Modal -->
{#if showModal}
	<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
	<div
		class="fixed inset-0 bg-black/70 flex items-center justify-center z-50"
		onclick={(e) => { if (e.target === e.currentTarget) showModal = false; }}
		onkeydown={(e) => { if (e.key === 'Escape') showModal = false; }}
		role="dialog"
		aria-modal="true"
		tabindex="-1"
	>
		<div class="bg-panel border border-border rounded-2xl p-7 w-full max-w-sm">
			<h2 class="text-base font-semibold mb-1">New Tenant</h2>
			<p class="text-[13px] text-muted mb-6">Provision a terminal instance for a user.</p>

			{#if provisionError}
				<div class="mb-4 text-[13px] text-red-400">{provisionError}</div>
			{/if}

			<form onsubmit={(e) => { e.preventDefault(); provision(); }}>
				<label for="uid" class="block text-[12px] text-muted mb-1.5">User ID</label>
				<input
					id="uid"
					type="text"
					bind:value={userId}
					placeholder="user-123"
					class="w-full px-3 py-2 text-[13px] bg-surface border border-border rounded-lg text-white placeholder:text-muted/40 focus:outline-none focus:border-white/20 transition-colors"
				/>
				<div class="flex justify-end gap-2 mt-6">
					<button type="button" onclick={() => (showModal = false)} class="px-4 py-2 text-[13px] text-muted hover:text-white transition-colors">Cancel</button>
					<button type="submit" disabled={provisioning || !userId.trim()} class="px-4 py-2 text-[13px] font-medium bg-white text-black rounded-lg hover:bg-white/90 transition-colors disabled:opacity-30">
						{provisioning ? 'Creating...' : 'Create'}
					</button>
				</div>
			</form>
		</div>
	</div>
{/if}
