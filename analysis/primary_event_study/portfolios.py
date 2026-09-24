"""nested portfolio sorts and five Matplotlib figures."""
from __future__ import annotations

import hashlib
from itertools import product

import numpy as np
import pandas as pd
from scipy.stats import t

from .core import DIVISIONS, equal_count_quintiles, write_csv


def summarize(group,variable):
    y=group[variable].astype(float)
    n=len(y)
    firms=group.cik.nunique()
    if not n:
        return {'n':0,'firms':0,'mean':None,'se_firm_clustered':None,'ci_low':None,'ci_high':None,
                'zero_scrisk_count':0,'zero_resolution_count':0,'sic_divisions':0}
    mean=float(y.mean())
    if firms>=2:
        cluster_sums=(y-mean).groupby(group.cik).sum()
        se=float(np.sqrt(firms/(firms-1)*np.sum(cluster_sums**2))/n)
        margin=float(t.ppf(.975,firms-1)*se)
    else:
        se=margin=None
    return {'n':n,'firms':int(firms),'mean':mean,'se_firm_clustered':se,
            'ci_low':mean-margin if margin is not None else None,
            'ci_high':mean+margin if margin is not None else None,
            'zero_scrisk_count':int(group.scrisk_zero.sum()),
            'zero_resolution_count':int(group.resolution_zero.sum()),'sic_divisions':int(group.sic_division.nunique())}


def build_portfolios(frame,output,make_charts=True,sample_label='Confirmed-call sample'):
    columns=['SCRisk','Resolution','CAR_0_1','CAR_2_60']
    eligible=frame.loc[frame.portfolio_eligible].copy()
    thresholds=[]
    for name in columns:
        frame[name+'_winsor']=np.nan
        if len(eligible):
            lo,hi=np.quantile(eligible[name].astype(float),[.01,.99],method='linear')
            eligible[name+'_winsor']=eligible[name].clip(lo,hi)
            frame.loc[eligible.index,name+'_winsor']=eligible[name+'_winsor']
            thresholds.append({'variable':name,'lower_percentile':.01,'upper_percentile':.99,
                               'lower_threshold':float(lo),'upper_threshold':float(hi),'n':len(eligible),
                               'clipped_below':int((eligible[name]<lo).sum()),'clipped_above':int((eligible[name]>hi).sum()),
                               'quantile_method':'linear'})
    eligible['portfolio_tie_key']=eligible.call_id.map(lambda x:hashlib.sha256(('portfolio-ties-v1|'+x).encode()).hexdigest())
    eligible['SCRisk_quintile']=equal_count_quintiles(eligible,'SCRisk_winsor',['sic_division'])
    eligible['Resolution_quintile']=equal_count_quintiles(eligible,'Resolution_winsor',['sic_division','SCRisk_quintile'])
    for column in ['portfolio_tie_key','SCRisk_quintile','Resolution_quintile']:
        frame[column]=eligible[column].reindex(frame.index)
    assert eligible.SCRisk_quintile.notna().all() and eligible.Resolution_quintile.notna().all()
    audit=[]
    for division,g in eligible.groupby('sic_division'):
        counts=g.SCRisk_quintile.value_counts().reindex(range(1,6),fill_value=0)
        assert counts.max()-counts.min()<=1
        for q in range(1,6):
            nested=g[g.SCRisk_quintile==q]
            counts2=nested.Resolution_quintile.value_counts().reindex(range(1,6),fill_value=0)
            assert counts2.max()-counts2.min()<=1
            audit.append({'sic_division':division,'SCRisk_quintile':q,'n':len(nested),
                          'resolution_min_cell':int(counts2.min()),'resolution_max_cell':int(counts2.max()),
                          'scrisk_zero_count':int(nested.scrisk_zero.sum()),
                          'resolution_zero_count':int(nested.resolution_zero.sum()),
                          'small_nested_stratum':len(nested)<5})
    write_csv(output/'winsorization_thresholds.csv',thresholds)
    write_csv(output/'quintile_balance_audit.csv',audit)
    eligible[['call_id','cik','historical_ticker','quarter_label','sic_4digit','sic_division','portfolio_tie_key',
              'SCRisk_quintile','Resolution_quintile','scrisk_zero','resolution_zero']+
             [v for c in columns for v in [c,c+'_winsor']]].to_csv(output/'quintile_assignments.csv',index=False,float_format='%.17g')
    coverage=[]
    for _,_,division in DIVISIONS:
        group=frame[frame.sic_division==division]
        included=group[group.portfolio_eligible]
        coverage.append({'sic_division':division,'all_source_calls':len(group),'car_joint_eligible':int(group.car_joint_eligible.sum()),
                         'portfolio_calls':len(included),'portfolio_companies':int(included.cik.nunique()),
                         'zero_scrisk':int(included.scrisk_zero.sum()),'zero_resolution':int(included.resolution_zero.sum())})
    write_csv(output/'sic_division_coverage.csv',coverage)
    tables={}
    specs=[('01_car_0_1_by_scrisk','SCRisk_quintile','CAR_0_1_winsor'),
           ('02_car_0_1_by_resolution','Resolution_quintile','CAR_0_1_winsor'),
           ('03_car_0_1_heatmap',None,'CAR_0_1_winsor'),
           ('04_car_2_60_by_scrisk','SCRisk_quintile','CAR_2_60_winsor'),
           ('05_car_2_60_heatmap',None,'CAR_2_60_winsor')]
    for name,quintile,variable in specs:
        records=[]
        if quintile:
            for q in range(1,6):
                records.append({quintile:q,**summarize(eligible[eligible[quintile]==q],variable)})
        else:
            for sq,rq in product(range(1,6),repeat=2):
                records.append({'SCRisk_quintile':sq,'Resolution_quintile':rq,
                                **summarize(eligible[(eligible.SCRisk_quintile==sq)&(eligible.Resolution_quintile==rq)],variable)})
        write_csv(output/(name+'.csv'),records)
        tables[name]=records
    if make_charts and len(eligible): render_charts(tables,output,len(eligible),int(eligible.cik.nunique()),sample_label)
    return frame,{'n':len(eligible),'companies':int(eligible.cik.nunique()),
                  'population':'joint CAR(0,1) and CAR(2,60) eligible with point-in-time SIC division and valid scores',
                  'winsorization':'global 1st/99th percentiles within portfolio-eligible sample, linear quantiles; originals retained',
                  'thresholds':thresholds,'scrisk_sort':'within SIC division; all observations including raw zeros',
                  'resolution_sort':'within SIC division and SCRisk quintile',
                  'ties':'ascending SHA256(portfolio-ties-v1|call_id), then call_id; independent of outcomes',
                  'quintile_formula':'floor(5 * zero_based_rank / group_size) + 1; counts differ by at most one',
                  'small_strata':'all rows retained; empty quintiles possible when group_size < 5',
                  'uncertainty':'95% t intervals using one-way CIK-clustered SE for equal-call-weight mean; fixed assignments',
                  'uncertainty_limit':'does not account for common-date cross-firm correlation or uncertainty in dictionary reconstruction',
                  'zero_scrisk_included':int(eligible.scrisk_zero.sum()),'zero_resolution_included':int(eligible.resolution_zero.sum())}


def render_charts(tables,output,n,firms,sample_label='Confirmed-call sample'):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.colors import TwoSlopeNorm
    from matplotlib.ticker import FuncFormatter
    plt.rcParams.update({'font.family':'DejaVu Serif','font.size':10,'axes.spines.top':False,
                         'axes.spines.right':False,'figure.dpi':130,'savefig.dpi':220,
                         'svg.hashsalt':'primary-event-study-v1'})
    captions=f'{sample_label}: {n:,} calls, {firms:,} firms. Variables winsorized at 1% and 99%.'
    for name,rows in tables.items():
        long='2_60' in name
        window='(2,60)' if long else '(0,1)'
        if 'heatmap' in name:
            fig,ax=plt.subplots(figsize=(7.7,6.6))
            means=np.array([r['mean'] if r['mean'] is not None else np.nan for r in rows]).reshape(5,5)*100
            bound=max(float(np.nanmax(np.abs(means))),.01)
            image=ax.imshow(means,cmap='RdBu',norm=TwoSlopeNorm(vmin=-bound,vcenter=0,vmax=bound),aspect='equal')
            for k,r in enumerate(rows):
                i,j=divmod(k,5)
                value=means[i,j]
                label=f'{value:+.2f}%\nn={r["n"]:,}' if np.isfinite(value) else 'No calls\nn=0'
                color='white' if np.isfinite(value) and abs(value)>.62*bound else '#202020'
                ax.text(j,i,label,ha='center',va='center',color=color,fontsize=10)
            ax.set_xticks(range(5),[f'Q{i}' for i in range(1,6)])
            ax.set_yticks(range(5),[f'Q{i}' for i in range(1,6)])
            ax.set_xlabel('Resolution quintile (low to high)')
            ax.set_ylabel('SCRisk quintile (low to high)')
            ax.set_title(f'Mean CAR{window}: SCRisk × Resolution',pad=15)
            colorbar=fig.colorbar(image,ax=ax,shrink=.82,pad=.035)
            colorbar.set_label('Mean cumulative abnormal return (%)')
            fig.text(.07,.075,captions,fontsize=8)
            fig.text(.07,.048,'SCRisk sorted within SIC division; Resolution sorted within division and SCRisk quintile.',fontsize=8)
            fig.text(.07,.023,'Cell-level firm-clustered 95% intervals are reported in the companion table.',fontsize=8)
            fig.subplots_adjust(bottom=.18,left=.13,right=.88,top=.90)
        else:
            resolution='resolution' in name
            label='Resolution' if resolution else 'SCRisk'
            fig,ax=plt.subplots(figsize=(7.7,5.2))
            mean=np.array([r['mean'] for r in rows],dtype=float)*100
            low=np.array([r['ci_low'] for r in rows],dtype=float)*100
            high=np.array([r['ci_high'] for r in rows],dtype=float)*100
            ax.bar(range(1,6),mean,color='#9eb4c4',edgecolor='#2b4557',linewidth=.7,width=.62,zorder=3)
            ax.errorbar(range(1,6),mean,yerr=np.vstack([mean-low,high-mean]),fmt='none',color='#202020',capsize=4,lw=1.2,zorder=4,label='95% interval, clustered by firm')
            ax.axhline(0,color='#333333',lw=.8)
            ax.grid(axis='y',alpha=.18,zorder=0)
            ax.set_xticks(range(1,6),[f'Q{i}\nn={r["n"]:,}' for i,r in enumerate(rows,1)])
            ax.set_xlabel(f'{label} quintile (low to high)',labelpad=9)
            ax.set_ylabel(f'Mean CAR{window} (%)')
            ax.yaxis.set_major_formatter(FuncFormatter(lambda v,p:f'{v:.2f}'))
            ax.set_title(f'Mean CAR{window} by {label} quintile',pad=17)
            ax.legend(loc='best',frameon=False,fontsize=8)
            fig.text(.085,.065,captions,fontsize=8)
            fig.text(.085,.028,'All zero scores included. Equal-call weights; deterministic ties; common sample across panels.',fontsize=8)
            fig.subplots_adjust(bottom=.24,left=.14,right=.97,top=.87)
        fig.savefig(output/(name+'.png'))
        fig.savefig(output/(name+'.svg'),metadata={'Date':None})
        plt.close(fig)
